"""Visual and workflow contracts for the compact OrcAgent Token Launch UI.

Isolated Flask test client; no RPC, Phantom approval, mint or spend.
"""
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch
from solders.keypair import Keypair
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_token_launch import setup

def test_token_launch_ui():
    tmp,app,d=setup()
    client=app.test_client()
    assert client.get('/token-launch').status_code==302
    with client.session_transaction() as sess:
        sess['wallet']=str(Keypair().pubkey())
        sess['csrf_token']='test-csrf'
    for flags in ({'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'0'},
                  {'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'1'}):
        with patch.dict(os.environ,flags):
            result=client.get('/token-launch')
            assert result.status_code==200
            html=result.get_data(as_text=True)
            for token in ('id="tl-form"','id="tl-name"','id="tl-symbol"',
                'id="tl-description"','id="tl-image"','id="tl-ack"',
                'id="tl-save"','id="tl-mine"','id="tl-dialog"',
                'id="stat-all"','id="stat-usdc"','id="stat-sol"',
                'id="all-tab"','id="mine-tab"','id="cards"','id="search"',
                'id="pair"','id="tl-community-fields"','Creator + Community Rewards',
                'id="tl-creator-earnings"','id="tl-available-usdc"','id="tl-claimed-usdc"',
                'id="tl-global-claim-history"','id="tl-refresh-earnings"',
                'id="tl-claim-now"','id="tl-recent-earnings"','id="tl-creator-share"'):
                assert token in html,token
            assert re.search(r'name="tl-mode" value="creator" checked',html)
            assert re.search(r'id="tl-image"[^>]*required',html)
            assert 'Network + protocol fees' in html and 'OrcAgent launch fee' in html
            assert 'Creator Earnings' in html and 'Earnings from tokens you created on OrcAgent.' in html
            assert 'Pump.fun' not in html and 'PumpSwap' not in html and 'Pump fees' not in html
            assert 'https://phantom.app/ul/v1/signAndSendTransaction' not in html
            assert re.search(r'token-launch-redesign\.css\?v=\d{10}',html)
            assert re.search(r'token-launch(?:es)?\.js\?v=\d{10}',html)
            if flags['ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED']=='1':
                assert 'Continue to approve' in html
                assert 'Preflight mode' not in html
            else:
                assert 'Preflight mode' in html and 'Save launch draft' in html
    directory=client.get('/launches')
    assert directory.status_code==200
    markup=directory.get_data(as_text=True)
    for token in ('Launch your','id="stat-all"','id="stat-usdc"',
        'id="stat-sol"','id="all-tab"','id="mine-tab"',
        'id="search"','id="pair"','/token-launch#tl-form'):
        assert token in markup,token
    assert re.search(r'token-launch-redesign\.css\?v=\d{10}',markup)
    js=(ROOT/'static/token-launch.js').read_text()
    assert "readyToApprove=data.draft" in js
    assert "await launchStage(readyToApprove,'create')" in js
    assert "var result=await dialog(title,details" in js
    assert "quote_asset:choice('tl-asset')" in js
    assert "reward_mode:mode" in js
    assert "var draftNonce=''" in js
    assert 'Trade on OrcAgent' in js and 'View on Pump' not in js
    directory_js=(ROOT/'static/token-launches.js').read_text()
    assert 'Trade on OrcAgent' in directory_js and 'Trade on Pump' not in directory_js
    assert "'/live-market?mint='+encodeURIComponent(data.mint)" in directory_js
    assert "'/live-market?mint='+encodeURIComponent(row.mint)" in js
    assert "'/api/token-launch/creator-earnings'" in js
    assert "'/api/token-launch/creator-fees'" in js
    assert 'No live USDC Creator Rewards token yet.' not in js
    assert 'tl-token-fee-overview' in js and 'tl-claim-history-' in js
    assert 'Solscan ↗' in js and 'Refresh available' in js
    assert 'creatorClaimLaunch' in js and "$('tl-claim-now').addEventListener" in js
    # Recent activity: the latest real claims (expired never-approved attempts left out).
    assert "renderClaimRows($('tl-recent-earnings'),history.filter(function(c){return !isExpired(c)}).slice(0,3),true," in js
    assert 'Pump.fun' not in js and 'PumpSwap' not in js and 'Pump fees' not in js and 'Pump transaction' not in js
    css=(ROOT/'static/token-launch-redesign.css').read_text()
    assert '.tl-saved>.tl-section-head{display:none}' in css
    print('PASS quick-launch hero, live stats, responsive form, real reward choices, wallet approval')
    print('PASS saved drafts, verified directory and versioned assets preserve API compatibility')
    tmp.cleanup()

if __name__=='__main__':
    test_token_launch_ui()
