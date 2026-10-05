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
DASH = (ROOT / 'dashboard.py').read_text()


def fake_dashboard():
    f = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    f.close()
    conn = sqlite3.connect(f.name)
    conn.executescript('''
      CREATE TABLE users(id INTEGER PRIMARY KEY,wallet_address TEXT,bsc_wallet_address TEXT);
      CREATE TABLE open_positions(user_id INTEGER,mint_address TEXT,symbol TEXT,amount REAL,buy_price REAL,spend REAL,chain TEXT,opened_at REAL,base_currency TEXT);
      INSERT INTO users VALUES(7,'session','0xevm');
      INSERT INTO open_positions VALUES(7,'0xtoken','TOK',2,3,6,'base',1,'USDC');
      INSERT INTO open_positions VALUES(7,'solmint','SOLPOS',1,4,4,'solana',1,'SOL');
    ''')
    conn.commit(); conn.close()
    d = types.SimpleNamespace()
    d.DB_FILE=f.name
    d.EVM_CHAINS={
      'bsc':{'usdc':'0xbsc'}, 'base':{'usdc':'0xbase'},
      'arbitrum':{'usdc':'0xarb'}, 'polygon':{'usdc':'0xpoly'},
      'robinhood':{'usdc':'0xhood'},
    }
    d.ACTIVE_EVM_CHAINS={}
    d._get_trading_wallet_address=lambda w:'soltrader'
    d._wallet_tokens_cache={}
    d.SOL_MINT='So11111111111111111111111111111111111111112'
    d.USDC_MINT='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
    d._fetch_wallet_tokens=lambda wallet,onchain:{'tokens':[
      {'symbol':'SOL','mint':d.SOL_MINT,'amount':1,'price_usd':100,'value_usd':100},
      {'symbol':'USDC','mint':d.USDC_MINT,'amount':20,'price_usd':1,'value_usd':20},
      {'symbol':'ABC','mint':'abc','amount':2,'price_usd':5,'value_usd':10},
    ]}
    d._get_solana_usdc_balance=lambda addr,**kwargs:20
    balances={'bsc':5,'base':10,'arbitrum':0,'polygon':2,'robinhood':3}
    d.get_evm_usdc_balance=lambda addr,chain:balances[chain]
    d.get_token_data=lambda addr,chain=None:{'symbol':'TOK','name':'Token','price':4}
    d._sol_price_usd=100
    d._get_user_sol=lambda addr:1
    d.SOL_NETWORK_RESERVE=.005
    return d


def test_snapshot_has_one_authoritative_total():
    d=fake_dashboard()
    snap=pf._portfolio_snapshot(d,'session',bust=True)
    # OrcAgent is Solana-only: only Solana USDC and SPL assets count.
    assert snap['stable']['total_usdc'] == 20
    assert snap['available_to_trade_usdc'] == 20
    assert snap['stable']['evm_chains'] == {}
    assert snap['sol']['value_usd'] == 100
    assert snap['other_assets_value_usd'] == 10
    assert snap['total_usd'] == 130
    assert snap['total_sol'] == 1.3
    assert snap['available_to_trade_sol'] == .995
    assert snap['trading_currency'] == 'SOL'
    assert snap['sol']['in_positions_sol'] == 4


def test_legacy_evm_position_stays_in_db_but_not_active_portfolio():
    d=fake_dashboard()
    snap=pf._portfolio_snapshot(d,'session',bust=True)
    assert not [x for x in snap['assets'] if x.get('chain')=='base']
    con=sqlite3.connect(d.DB_FILE)
    row=con.execute("SELECT mint_address FROM open_positions WHERE chain='base'").fetchone()
    con.close()
    assert row and row[0]=='0xtoken'


def test_snapshot_endpoint_is_registered():
    assert "@app.get('/api/portfolio/snapshot')" in MOD


def test_wallet_three_loaders_share_snapshot_request():
    assert 'window.OrcAgentGetPortfolioSnapshot=_getPortfolioSnapshot' in WALLET
    bal=WALLET[WALLET.index('function loadBalance()'):WALLET.index('loadBalance()',WALLET.index('function loadBalance()')+10)]
    usdc=WALLET[WALLET.index('function loadUsdcSummary()'):WALLET.index('loadUsdcSummary()',WALLET.index('function loadUsdcSummary()')+10)]
    toks=WALLET[WALLET.index('function loadTokens(bust)'):WALLET.index('\n\nloadTokens()',WALLET.index('function loadTokens(bust)'))]
    assert '_getPortfolioSnapshot(false)' in bal and '/api/wallet/balance' not in bal
    assert '_getPortfolioSnapshot(false)' in usdc and '/api/wallet/usdc-summary' not in usdc
    assert '_getPortfolioSnapshot(!!bust)' in toks
    assert "fetch('/api/wallet/tokens'" not in toks  # one authoritative scan, no racing partial list


def test_total_controller_no_longer_fans_out_three_requests():
    block=CTRL[CTRL.index('function refreshValue'):CTRL.index('function refreshHoldings')]
    assert '/api/portfolio/snapshot' in block
    assert '/api/wallet/usdc-summary' not in block
    assert '/api/wallet/tokens' not in block
    assert '/api/wallet/balance' not in block
    assert 'Promise.allSettled' not in block


def test_background_snapshot_uses_provider_failover_not_raw_public_rpc():
    block=DASH[DASH.index("def _snapshot_portfolios"):DASH.index("@app.route('/api/admin/recover-fees'")]
    assert "sol_balance = _get_user_sol(wallet)" in block
    assert "r.json()['result']['value']" not in block
    assert "threading.Semaphore(3)" in block


def test_partial_refresh_keeps_last_confirmed_snapshot():
    d=fake_dashboard()
    first=pf._portfolio_snapshot(d,'session',bust=True)
    d._fetch_wallet_tokens=lambda *args: (_ for _ in ()).throw(RuntimeError('rpc down'))
    second=pf._portfolio_snapshot(d,'session',bust=True)
    assert second['total_usd']==first['total_usd']
    assert second['stale'] is True
    assert 'full_token_index' in second['unavailable']


if __name__=='__main__':
    for name in sorted(n for n in globals() if n.startswith('test_')):
        globals()[name]()
        print('PASS',name)
    print('ALL PORTFOLIO SNAPSHOT REGRESSIONS PASSED')
