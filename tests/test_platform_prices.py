"""Public market price replies, exact identity, freshness and no feed write-lock I/O."""
import sqlite3
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import requests
import platform_prices as p
import platform_assistant as agent
import test_platform_assistant as fixtures

MINT='So11111111111111111111111111111111111111112'
OTHER='So11111111111111111111111111111111111111113'

def response(body,status=200):
    return SimpleNamespace(status_code=status,json=lambda:body)

def pair(mint=MINT,symbol='CATE',price='0.00123',liq=100000,chain='solana'):
    return dict(chainId=chain,baseToken=dict(address=mint,symbol=symbol,name='Cate'),
                priceUsd=price,liquidity=dict(usd=liq))

class Prices(unittest.TestCase):
    def setUp(self):
        p._CACHE.clear();p._CALLS.clear()
    def test_recognizes_major_names_and_tickers_in_both_languages(self):
        for text,coin in [('what is the price of Solana?','solana'),('SOL price?','solana'),
                          ('wat is de koers van btc?','bitcoin'),('price of $BTC','bitcoin')]:
            self.assertEqual(p.query(text)['values'],[coin])
        self.assertEqual(p.query('price of SOL and BTC')['values'],['solana','bitcoin'])
        self.assertEqual(p.query('BTC price in EUR')['currency'],'eur')
    def test_recognizes_any_market_ticker_name_and_preserves_contract_case(self):
        self.assertEqual(p.query('what is the price of cate token?')['value'],'CATE')
        self.assertEqual(p.query('$Bonk price now')['value'],'BONK')
        self.assertEqual(p.query('what is the price of '+MINT)['value'],MINT)
        self.assertEqual(p.query('prijs van WIF')['value'],'WIF')
        self.assertEqual(p.query('price of Attention Inu?')['value'],'ATTENTION INU')
    def test_forecasts_platform_costs_and_unrelated_comments_are_not_quotes(self):
        for text in ['will BTC price reach 100 tomorrow?', 'predict SOL price',
                     'what are the platform fees?', 'how do I buy tokens?', 'hi']:
            self.assertIsNone(p.query(text))
    def test_major_prices_currency_source_and_timestamp(self):
        stamp=time.time()
        q=p.query('SOL and BTC price in EUR?')
        def get(url,**kw):
            self.assertEqual(kw['params']['vs_currencies'],'eur')
            self.assertFalse(kw['allow_redirects'])
            return response({'solana':{'eur':145,'last_updated_at':stamp},
                             'bitcoin':{'eur':91000,'last_updated_at':stamp}})
        snap=p.fetch(q,get=get);topic,text=p.render(q,snap)
        self.assertEqual(topic,'market_price')
        for part in ('SOL: 145.00 EUR','BTC: 91,000.00 EUR','UTC','CoinGecko'):
            self.assertIn(part,text)
    def test_stale_major_data_and_nonfinite_prices_are_rejected(self):
        q=p.query('BTC price')
        for value,stamp in [(10,time.time()-300),(float('nan'),time.time()),(float('inf'),time.time()),(0,time.time())]:
            p._CACHE.clear()
            snap=p.fetch(q,get=lambda *a,**k:response({'bitcoin':{'usd':value,'last_updated_at':stamp}}))
            self.assertIsNone(snap)
    def test_deepest_pool_for_exact_mint_and_chain(self):
        q=p.query('price '+MINT)
        rows=[pair(price='1',liq=5),pair(price='2',liq=100),
              pair(mint=OTHER,price='999',liq=1000000),pair(price='888',chain='ethereum')]
        snap=p.fetch(q,get=lambda *a,**k:response({'pairs':rows}))
        self.assertEqual(snap['rows'][0]['price'],2)
        self.assertEqual(snap['rows'][0]['mint'],MINT)
        text=p.render(q,snap)[1]
        self.assertIn(MINT,text)
        self.assertIn('DexScreener',text)
        self.assertIn('/live-market',text)
    def test_duplicate_pools_are_not_ambiguous_but_different_mints_are(self):
        q=p.query('price of $CATE')
        snap=p.fetch(q,get=lambda *a,**k:response({'pairs':[pair(),pair(liq=200000),pair(mint=OTHER)]}))
        self.assertEqual(snap['kind'],'choice')
        self.assertTrue(p.render(q,snap)[1].startswith('Do you mean $CATE?'))
    def test_retrieved_age_cannot_be_reset_by_cache(self):
        q=p.query('price '+MINT)
        snap=dict(kind='prices',rows=[dict(mint=MINT,symbol='CATE',price=.01,observed=time.time()-121)],
                  currency='usd',source='DexScreener')
        self.assertEqual(p.render(q,snap)[1],p.UNAVAILABLE)
    def test_timeout_rate_limit_and_invalid_response_have_honest_fallback(self):
        q=p.query('BTC price')
        with patch.object(p.requests,'get',side_effect=requests.Timeout):
            self.assertIsNone(p.fetch(q))
        self.assertEqual(p.render(q,None)[1],p.UNAVAILABLE)
        p._CACHE.clear()
        self.assertIsNone(p.fetch(q,get=lambda *a,**k:response({},429)))
    def test_cache_shares_fetch_and_does_not_cache_forever(self):
        q=p.query('price '+MINT);calls=[]
        def get(*a,**k):
            calls.append(a);return response({'pairs':[pair()]})
        self.assertEqual(p.fetch(q,get=get),p.fetch(q,get=get))
        self.assertEqual(len(calls),1)
        key=repr(sorted(q.items()));old=p._CACHE[key]
        p._CACHE[key]=(time.time()-21,old[1],old[2])
        p.fetch(q,get=get)
        self.assertEqual(len(calls),2)
    def test_no_unsupported_currency_claim(self):
        q=p.query('CATE price in EUR')
        snap=p.fetch(q,get=lambda *a,**k:self.fail('no unsupported quote request'))
        self.assertIn('in USD',p.render(q,snap)[1])
        self.assertEqual(p.query('BTC price in GBP')['kind'],'currency')
    def test_fake_major_tokens_cannot_impersonate_native_btc(self):
        q=p.query('$BTC price')
        self.assertEqual(q['kind'],'major')
        self.assertEqual(q['values'],['bitcoin'])
    def test_tiny_prices_do_not_round_to_zero(self):
        q=p.query('price '+MINT)
        snap=p.fetch(q,get=lambda *a,**k:response({'pairs':[pair(price='0.000000000001')]}))
        self.assertNotIn('CATE: 0 USD',p.render(q,snap)[1])

class Integration(unittest.TestCase):
    setUp=fixtures.Assistant.setUp
    tearDown=fixtures.Assistant.tearDown
    source=fixtures.Assistant.source
    def test_reply_retrieves_quote_outside_db_write_transaction(self):
        p._CACHE.clear();p._CALLS.clear()
        def dex_get(*a,**kw):
            with sqlite3.connect(self.db,timeout=.1) as c:
                c.execute('BEGIN IMMEDIATE')
            return response({'pairs':[pair()]})
        self.d._dex_get=dex_get
        source=self.source('@orcagent what is the price of '+MINT+'?')
        rid=agent.reply_to(self.d,source,'member',self.now)
        with sqlite3.connect(self.db) as c:
            message=c.execute('SELECT message FROM feed_replies WHERE id=?',(rid,)).fetchone()[0]
        self.assertIn('0.00123 USD',message)
        self.assertIn(MINT,message)
    def test_post_and_nested_price_answer_use_same_path(self):
        p._CACHE.clear();p._CALLS.clear()
        self.d._dex_get=lambda *a,**k:response({'pairs':[pair()]})
        with sqlite3.connect(self.db) as c:
            post=c.execute('INSERT INTO feed_posts(wallet,content,created_at) VALUES(?,?,?)',
                ('member','@orcagent $CATE price?','2026-10-04 00:00:00')).lastrowid
        rid=agent.reply_to_post(self.d,post,'member',self.now)
        with sqlite3.connect(self.db) as c:
            text=c.execute('SELECT message FROM feed_replies WHERE id=?',(rid,)).fetchone()[0]
        self.assertIn('CATE:',text)
    def test_unauthenticated_and_private_threads_never_fetch_prices(self):
        self.d._dex_get=lambda *a,**k:self.fail('must not fetch')
        source=self.source('@orcagent price '+MINT,post='g1')
        self.assertIsNone(agent.reply_to(self.d,source,'member',self.now))
        source=self.source('@orcagent price '+MINT)
        self.assertIsNone(agent.reply_to(self.d,source,'wrong-wallet',self.now))
    def test_chooser_handles_prefix_free_replies_and_selected_question(self):
        js=Path('static/dashboard.js').read_text()
        self.assertIn('(?:Automated · )?Do you mean',js)
        self.assertIn("what is the price?';",js)
        self.assertEqual(p.query('$CATE ('+MINT+') what is the price?')['value'],MINT)

if __name__=='__main__':
    unittest.main()
