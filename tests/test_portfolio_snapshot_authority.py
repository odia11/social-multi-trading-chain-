"""Side-effect-free regression tests for authoritative Portfolio snapshot."""
import sqlite3
import tempfile
import types
from pathlib import Path

import portfolio_multichain_holdings as pf

ROOT = Path(__file__).resolve().parents[1]
WALLET = (ROOT / 'templates' / 'wallet.html').read_text()
CTRL = (ROOT / 'static' / 'portfolio-multichain.js').read_text()
MOD = (ROOT / 'portfolio_multichain_holdings.py').read_text()


def fake_dashboard():
    f = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    f.close()
    conn = sqlite3.connect(f.name)
    conn.executescript('''
      CREATE TABLE users(id INTEGER PRIMARY KEY,wallet_address TEXT,bsc_wallet_address TEXT);
      CREATE TABLE open_positions(user_id INTEGER,mint_address TEXT,symbol TEXT,amount REAL,buy_price REAL,spend REAL,chain TEXT,opened_at REAL);
      INSERT INTO users VALUES(7,'session','0xevm');
      INSERT INTO open_positions VALUES(7,'0xtoken','TOK',2,3,6,'base',1);
      INSERT INTO open_positions VALUES(7,'solmint','SOLPOS',1,4,4,'solana',1);
    ''')
    conn.commit(); conn.close()
    d = types.SimpleNamespace()
    d.DB_FILE=f.name
    d.EVM_CHAINS={
      'bsc':{'usdc':'0xbsc'}, 'base':{'usdc':'0xbase'},
      'arbitrum':{'usdc':'0xarb'}, 'polygon':{'usdc':'0xpoly'},
      'robinhood':{'usdc':'0xhood'},
    }
    d._get_trading_wallet_address=lambda w:'soltrader'
    d._wallet_tokens_cache={}
    d._fetch_wallet_tokens=lambda wallet,onchain:{'tokens':[
      {'symbol':'SOL','mint':'So111','amount':1,'price_usd':100,'value_usd':100},
      {'symbol':'USDC','mint':'usdc','amount':20,'price_usd':1,'value_usd':20},
      {'symbol':'ABC','mint':'abc','amount':2,'price_usd':5,'value_usd':10},
    ]}
    d._get_solana_usdc_balance=lambda addr:20
    balances={'bsc':5,'base':10,'arbitrum':0,'polygon':2,'robinhood':3}
    d.get_evm_usdc_balance=lambda addr,chain:balances[chain]
    d.get_token_data=lambda addr,chain=None:{'symbol':'TOK','name':'Token','price':4}
    d._sol_price_usd=100
    return d


def test_snapshot_has_one_authoritative_total():
    d=fake_dashboard()
    snap=pf._portfolio_snapshot(d,'session',bust=True)
    # stable 40 + SOL 100 + ABC 10 + EVM TOK 8 = 158
    assert snap['stable']['total_usdc'] == 40
    assert snap['available_to_trade_usdc'] == 40
    assert snap['sol']['value_usd'] == 100
    assert snap['other_assets_value_usd'] == 18
    assert snap['total_usd'] == 158
    assert snap['sol']['in_positions_sol'] == 4


def test_evm_position_is_from_durable_db_not_process_memory():
    d=fake_dashboard()
    snap=pf._portfolio_snapshot(d,'session',bust=True)
    evm=[x for x in snap['assets'] if x.get('chain')=='base']
    assert len(evm)==1
    assert evm[0]['mint']=='0xtoken'
    assert evm[0]['usd_value']==8


def test_snapshot_endpoint_is_registered():
    assert "@app.get('/api/portfolio/snapshot')" in MOD


def test_wallet_three_loaders_share_snapshot_request():
    assert 'window.OrcAgentGetPortfolioSnapshot=_getPortfolioSnapshot' in WALLET
    bal=WALLET[WALLET.index('function loadBalance()'):WALLET.index('loadBalance()',WALLET.index('function loadBalance()')+10)]
    usdc=WALLET[WALLET.index('function loadUsdcSummary()'):WALLET.index('loadUsdcSummary()',WALLET.index('function loadUsdcSummary()')+10)]
    toks=WALLET[WALLET.index('function loadTokens(bust)'):WALLET.index('\n\nloadTokens()',WALLET.index('function loadTokens(bust)'))]
    assert '_getPortfolioSnapshot(false)' in bal and '/api/wallet/balance' not in bal
    assert '_getPortfolioSnapshot(false)' in usdc and '/api/wallet/usdc-summary' not in usdc
    assert '_getPortfolioSnapshot(!!bust)' in toks and '/api/wallet/tokens' not in toks


def test_total_controller_no_longer_fans_out_three_requests():
    block=CTRL[CTRL.index('function refreshValue'):CTRL.index('function refreshHoldings')]
    assert '/api/portfolio/snapshot' in block
    assert '/api/wallet/usdc-summary' not in block
    assert '/api/wallet/tokens' not in block
    assert '/api/wallet/balance' not in block
    assert 'Promise.allSettled' not in block


def test_partial_refresh_keeps_last_confirmed_snapshot():
    d=fake_dashboard()
    first=pf._portfolio_snapshot(d,'session',bust=True)
    d.get_evm_usdc_balance=lambda addr,chain: (_ for _ in ()).throw(RuntimeError('rpc down')) if chain=='base' else 0
    second=pf._portfolio_snapshot(d,'session',bust=True)
    assert second['total_usd']==first['total_usd']
    assert second['stale'] is True
    assert 'stable:base' in second['unavailable']


if __name__=='__main__':
    for name in sorted(n for n in globals() if n.startswith('test_')):
        globals()[name]()
        print('PASS',name)
    print('ALL PORTFOLIO SNAPSHOT REGRESSIONS PASSED')
