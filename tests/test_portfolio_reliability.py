import copy
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock
import portfolio_inventory as inv
import portfolio_multichain_holdings as pf

SOL='So11111111111111111111111111111111111111112'
USDC=inv._USDC
def account(owner,mint,raw,decimals=6):
    return {'account':{'data':{'parsed':{'info':{'owner':owner,'mint':mint,
        'tokenAmount':{'amount':str(raw),'decimals':decimals,'uiAmount':None}}}}}}

class PortfolioTests(unittest.TestCase):
    def setUp(self):
        inv._CACHE.clear();inv._LOCKS.clear();pf._SNAPSHOT_CACHE.clear();pf._SNAPSHOT_FLIGHTS.clear()
        self.tmp=tempfile.TemporaryDirectory();db=self.tmp.name+'/db'
        with sqlite3.connect(db) as c:
            c.executescript("CREATE TABLE users(id INTEGER,wallet_address TEXT);INSERT INTO users VALUES(1,'login');"
                "CREATE TABLE user_tokens(user_id INTEGER,token_address TEXT,avg_price REAL);"
                "CREATE TABLE open_positions(user_id INTEGER,spend REAL,chain TEXT,base_currency TEXT);")
        self.owner='OwnerCaseSensitive'
        self.data={'legacy':[account(self.owner,USDC,20000000),account(self.owner,'ABC',1000000)],
                   't2022':[account(self.owner,'ABC',1000000),account(self.owner,'tiny',1,12)]}
        self.failed=set();self.price_down=False
        self.calls=[];self.call_lock=threading.Lock();self.barrier=None
        def post(url,json,timeout):
            prog=json['params'][1]['programId']
            with self.call_lock:self.calls.append((url,prog))
            if self.barrier:self.barrier.wait(timeout=2)
            if prog in self.failed:return SimpleNamespace(status_code=429)
            return SimpleNamespace(status_code=200,json=lambda:{'result':{'value':copy.deepcopy(self.data[prog])}})
        def dex(url,timeout):
            names=url.rsplit('/',1)[1].split(',')
            rows=[] if self.price_down else [{'chainId':'solana','baseToken':{'address':m,'symbol':m},
                'priceUsd':str(100 if m==SOL else 5),'liquidity':{'usd':1000}} for m in names if m!='tiny']
            return SimpleNamespace(status_code=200,json=lambda:{'pairs':rows})
        self.d=SimpleNamespace(DB_FILE=db,SOL_MINT=SOL,USDC_MINT=USDC,
            TOKEN_PROGRAM_ID='legacy',TOKEN_2022_PROGRAM_ID='t2022',
            SOLANA_RPC='primary',_PROXY_RPCS=['fallback'],_wallet_tokens_cache={},
            requests=SimpleNamespace(post=post),_dex_get=dex,_get_user_sol=lambda a:1,
            _sol_price_usd=100,SOL_NETWORK_RESERVE=.005,
            _get_trading_wallet_address=lambda w:self.owner)
        inv.install(self.d)

    def tearDown(self):self.tmp.cleanup()
    def read(self):return inv.fetch(self.d,'login',self.owner)
    def bust(self):self.d._wallet_tokens_cache.clear()

    def test_both_programs_parallel_raw_amounts_and_tiny_holdings(self):
        self.barrier=threading.Barrier(2)
        result=self.read()
        assets={t['mint']:t for t in result['tokens']}
        self.assertEqual(assets['ABC']['amount'],2)
        self.assertEqual(assets['tiny']['amount'],1e-12)
        self.assertEqual(assets[USDC]['amount'],20)
        self.assertEqual(len(self.calls),2)
        self.assertTrue(result['inventory_complete'])
        self.assertFalse(result['valuation_complete'])

    def test_concurrent_clients_share_one_scan(self):
        with ThreadPoolExecutor(max_workers=8) as ex:
            results=list(ex.map(lambda _:self.read(),range(8)))
        self.assertEqual(len(self.calls),2)
        self.assertEqual(len(results),8)

    def test_program_outage_never_replaces_complete_inventory(self):
        first=self.read();self.bust();self.failed={'t2022'}
        later=self.read()
        self.assertEqual(later['tokens'],first['tokens'])
        self.assertTrue(later['stale']);self.assertFalse(later['inventory_complete'])

    def test_first_load_outage_is_unavailable_not_empty_wallet(self):
        self.failed={'legacy'}
        with self.assertRaises(RuntimeError):self.read()
        self.assertFalse(inv._CACHE)

    def test_confirmed_zero_removes_sold_tokens(self):
        self.read();self.bust();self.data={'legacy':[],'t2022':[]}
        result=self.read()
        self.assertEqual([t['mint'] for t in result['tokens']],[SOL])
        self.assertTrue(result['inventory_complete'])

    def test_price_failure_keeps_holdings_and_marks_estimates(self):
        first=self.read();self.bust();self.price_down=True
        later=self.read()
        self.assertEqual(len(later['tokens']),len(first['tokens']))
        self.assertIn('ABC',later['stale_price_mints'])
        self.assertFalse(later['valuation_complete'])

    def test_wallet_identity_is_part_of_cache_key(self):
        self.read();self.owner='ownercasesensitive'
        self.data={'legacy':[],'t2022':[]}
        later=self.read()
        self.assertEqual([t['mint'] for t in later['tokens']],[SOL])
        self.assertEqual(later['owner'],'ownercasesensitive')

    def test_invalid_native_balance_does_not_paint_zero(self):
        self.d._get_user_sol=lambda _:float('nan')
        with self.assertRaises(RuntimeError):self.read()

    def test_owner_mismatch_rejected(self):
        self.data['t2022']=[account('other-wallet','foreign',1)]
        with self.assertRaises(RuntimeError):self.read()

    def test_snapshot_prices_usdt_and_ticker_spoofs_by_mint(self):
        self.data['legacy'].append(account(self.owner,inv._USDT,10000000))
        snapshot=pf._portfolio_snapshot(self.d,'login',bust=True)
        self.assertEqual(snapshot['stable']['total_usdc'],20)
        self.assertEqual(snapshot['other_assets_value_usd'],20)
        self.assertEqual(snapshot['total_usd'],140)
        def tokens(*args):
            return {'inventory_complete':True,'tokens':[
                {'mint':SOL,'symbol':'SOL','amount':1,'price_usd':100,'value_usd':100},
                {'mint':'fake-usdc','symbol':'USDC','amount':2,'price_usd':3,'value_usd':6}]}
        self.d._fetch_wallet_tokens=tokens
        snap=pf._portfolio_snapshot(self.d,'login',bust=True)
        self.assertEqual(snap['stable']['total_usdc'],0)
        self.assertEqual(snap['other_assets_value_usd'],6)

    def test_snapshot_incomplete_cannot_lower_total(self):
        first=pf._portfolio_snapshot(self.d,'login',bust=True)
        self.failed={'legacy'}
        later=pf._portfolio_snapshot(self.d,'login',bust=True)
        self.assertEqual(later['total_usd'],first['total_usd'])
        self.assertEqual(later['assets'],first['assets'])
        self.assertTrue(later['stale']);self.assertTrue(later['partial'])

    def test_wrapped_sol_is_distinct_from_native_sol(self):
        self.data['legacy'].append(account(self.owner,SOL,2000000000,9))
        snap=pf._portfolio_snapshot(self.d,'login',bust=True)
        self.assertEqual(snap['sol']['amount'],1)
        wrapped=next(t for t in snap['assets'] if t['symbol']=='WSOL')
        self.assertEqual(wrapped['amount'],2)
        self.assertEqual(snap['total_usd'],330)
        self.assertEqual(snap['other_assets_value_usd'],210)

    def test_no_asset_cap_at_250(self):
        self.data['legacy']=[account(self.owner,'mint-'+str(i),1) for i in range(300)]
        self.data['t2022']=[]
        self.assertEqual(len(self.read()['tokens']),301)

if __name__=='__main__':unittest.main()
