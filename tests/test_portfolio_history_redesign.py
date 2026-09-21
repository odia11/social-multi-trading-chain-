"""Approved mobile History UI and read-only Solana wallet event integration."""
import os
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
import portfolio_wallet_activity as wallet_activity

ROOT = Path(__file__).resolve().parents[1]
WALLET = (ROOT/'templates/wallet.html').read_text()
JS = (ROOT/'static/portfolio-history-redesign.js').read_text()
CSS = (ROOT/'static/portfolio-history-redesign.css').read_text()
PORTFOLIO = (ROOT/'static/portfolio-redesign.js').read_text()
ENTRY = (ROOT/'app_entry.py').read_text()
USDC = wallet_activity.USDC
OWNER = '11111111111111111111111111111111'


def setup_app():
    temp = tempfile.TemporaryDirectory()
    db = os.path.join(temp.name,'test.sqlite')
    con=sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, wallet_address TEXT);
        INSERT INTO users VALUES (1,'11111111111111111111111111111111');
        CREATE TABLE tip_transactions (
            sender_wallet TEXT, recipient_wallet TEXT,
            sender_user_id INTEGER, recipient_user_id INTEGER,
            tx_hash TEXT);
        INSERT INTO tip_transactions VALUES
            ('11111111111111111111111111111111','recipient',1,2,'tip-sig');
    """)
    con.commit();con.close()
    app=Flask(__name__)
    d=SimpleNamespace(
        app=app, DB_FILE=db, _authenticated_wallet=lambda:OWNER,
        _get_trading_wallet_address=lambda wallet:OWNER)
    with patch.object(wallet_activity,'_wallet_events',return_value=[]):
        wallet_activity.install(d)
    return temp,d


def rpc_result(method, params):
    if method=='getTokenAccountsByOwner':
        return ({'value':[{'pubkey':'usdc-ata'}]},'mock')
    if method=='getSignaturesForAddress':
        if params[0] == OWNER:
            return ([{'signature':'tip-sig','blockTime':200,'err':None}], 'mock')
        return ([{'signature':'incoming','blockTime':400,'err':None},
                 {'signature':'swap','blockTime':300,'err':None},
                 {'signature':'failed','blockTime':250,'err':None},
                 {'signature':'tip-sig','blockTime':200,'err':None}], 'mock')
    if method=='getTransaction':
        sig=params[0]
        initial=1_000_000_000
        pre=[{'mint':USDC,'owner':OWNER,'uiTokenAmount':{'amount':'100000'}}]
        post=[{'mint':USDC,'owner':OWNER,'uiTokenAmount':{'amount':'600000'}}]
        if sig=='swap':
            pre[0]['uiTokenAmount']['amount']='600000'
            post[0]['uiTokenAmount']['amount']='200000'
        metadata={'err':{'InstructionError':[0,'Custom']} if sig=='failed' else None,
                  'preTokenBalances':pre,'postTokenBalances':post,
                  'preBalances':[initial],'postBalances':[initial-5000]}
        if sig=='swap': metadata['postBalances']=[initial+2500000]
        return ({'blockTime':400 if sig=='incoming' else 300,'meta':metadata,
                 'transaction':{'message':{'accountKeys':[{'pubkey':OWNER}]}}},'mock')
    raise AssertionError(method)


def test_wallet_events_are_actual_confirmed_canonical_usdc_only():
    temp,d=setup_app()
    try:
        with patch('portfolio_token_withdraw._rpc_call_any',side_effect=lambda _,method,params:rpc_result(method,params)):
            events=wallet_activity._wallet_events(d,OWNER)
        assert len(events)==1
        assert events[0]['type']=='receive'
        assert events[0]['amount']==0.5
        assert events[0]['status']=='confirmed'
        assert events[0]['tx_hash']=='incoming'
        assert events[0]['explorer_url'].startswith('https://solscan.io/tx/')
    finally:temp.cleanup()


def test_wallet_event_endpoint_requires_auth_and_caches_safe_history():
    temp,d=setup_app()
    try:
        wallet_activity._CACHE.clear()
        d._authenticated_wallet=lambda:None
        c=d.app.test_client()
        assert c.get('/api/portfolio/wallet-activity').status_code==401
        d._authenticated_wallet=lambda:OWNER
        with patch.object(wallet_activity,'_wallet_events',
                          return_value=[{'id':'verified','amount':0.25}]) as scan:
            r=c.get('/api/portfolio/wallet-activity')
            assert r.status_code==200 and r.json['events'][0]['id']=='verified'
            assert c.get('/api/portfolio/wallet-activity').json['events'][0]['id']=='verified'
            assert scan.call_count==1
    finally:temp.cleanup()


def test_ui_replaces_history_only_and_keeps_assets_and_bridge_execution():
    assert 'id="oa-history-page"' in WALLET
    for name in ['oa-h-recent','oa-h-filters','oa-h-days','oa-h-chain',
                 'oa-h-recent-toggle','oa-h-viewall']:
        assert 'id="'+name+'"' in WALLET
    for value in ['all','tips','swaps','wallet']:
        assert 'data-oa-h-filter="'+value+'"' in WALLET
    assert 'Bridge History' not in WALLET
    assert 'id="bridge-history-list"' not in WALLET
    assert 'function _loadBridgeHistory()' in WALLET  # bridge execution API unchanged
    assert 'body.oa-portfolio.pf-view-history .act-card' in CSS
    assert 'body.oa-portfolio.pf-view-history .wlt-hero' in CSS
    assert 'body.oa-portfolio .oa-h-page{display:none}' in CSS
    assert "if(b)showView(b.dataset.portfolioTab)" in PORTFOLIO
    assert "new CustomEvent('orcagent:portfolio-view'" in PORTFOLIO


def test_real_sources_scoped_to_user_not_mock_data():
    for path in ['/api/tips/mine?limit=100',
                 '/api/portfolio/transactions?limit=100',
                 '/api/portfolio/wallet-activity']:
        assert path in JS
    assert 'Promise.allSettled([tipRequest,tradeRequest])' in JS
    assert 'Number.isFinite' in JS
    assert "'submitted'" in JS and "'confirmed'" in JS
    assert "'View on blockchain ↗'" in JS
    assert 'No demo activity.' in JS


def test_date_groups_filters_and_accessible_accordions():
    for name in ['Today','Yesterday','This Week']:
        assert name in JS
    assert 'state.openDays' in JS
    assert "header.setAttribute('aria-expanded'" in JS
    assert "button.setAttribute('aria-expanded'" in JS
    assert "setAttribute('aria-pressed'" in JS
    assert 'scrollIntoView' in JS
    assert "classList.toggle('is-collapsed'" in JS


def test_no_synthetic_usd_sells_or_chains_in_wallet_events():
    assert "amount:buy&&Number.isFinite(Number(t.amount_usd))" in JS
    assert "unit:buy?'USDC':''" in JS
    assert 'For old sells, amount_usd' in JS
    assert "state.chain==='all'||e.chain===state.chain" in JS
    assert 'getSignaturesForAddress' in (ROOT/'portfolio_wallet_activity.py').read_text()
    assert 'getTransaction' in (ROOT/'portfolio_wallet_activity.py').read_text()
    assert 'sendTransaction' not in (ROOT/'portfolio_wallet_activity.py').read_text()


def test_orcagent_theme_and_readability():
    assert '--oa-h-gold:#f7b955' in CSS
    assert 'oa-h-icon.tip' in CSS and 'oa-h-icon.swap' in CSS
    assert '@media(max-width:630px)' in CSS
    assert 'overscroll-behavior:contain' not in CSS
    assert 'portfolio-history-redesign.css' in WALLET
    assert 'portfolio-history-redesign.js' in WALLET
    assert 'portfolio_wallet_activity' in ENTRY


if __name__=='__main__':
    for key in sorted(n for n in globals() if n.startswith('test_')):
        globals()[key]()
        print('PASS',key)
    print('ALL APPROVED HISTORY REDESIGN REGRESSIONS PASSED')
