"""Profile portfolio SOL display: role scoped and never a fake zero.

Run with PYTHONPATH=. venv/bin/python tests/test_profile_portfolio_balance.py.
No on-chain transfers, no real RPC/network, temporary SQLite database.
"""
import os
import sqlite3
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

import profile_portfolio_balance as mod


def setup():
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, 'profile-balance.sqlite')
    conn = sqlite3.connect(path)
    conn.executescript("""
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        wallet_address TEXT,
        is_profile_private INTEGER NOT NULL DEFAULT 0
    );
    INSERT INTO users VALUES (1, 'user-one', 0);
    INSERT INTO users VALUES (2, 'user-two', 1);
    """)
    conn.commit()
    conn.close()
    app = Flask(__name__)
    viewer = ['user-one']
    d = SimpleNamespace(
        app=app,
        DB_FILE=path,
        rate_limit=lambda *_: lambda function: function,
        _authenticated_wallet=lambda: viewer[0],
        _get_trading_wallet_address=lambda wallet: wallet,
        _get_user_sol=lambda wallet: (_ for _ in ()).throw(RuntimeError('rpc down')),
        SOL_NETWORK_RESERVE=0.005,
        _get_solana_sol_balance=lambda wallet, **kwargs: (_ for _ in ()).throw(RuntimeError('rpc down')),
    )
    mod.install(d)
    return tmp, app.test_client(), viewer


def test_public_balance_is_for_profile_user_not_viewer():
    temp, client, viewer = setup()
    try:
        with patch('portfolio_multichain_holdings._portfolio_snapshot',
                   return_value={'total_sol': 1.39,
                                 'available_to_trade_sol': 0.13,
                                 'stable': {'solana_sol': 0.13, 'evm_chains': {}},
                                 'stale': False}) as snapshot:
            response = client.get('/api/profile/1/portfolio-balance')
            assert response.status_code == 200
            data = response.json
            assert data['ok'] is True
            assert data['portfolio_value_sol_approx'] == 1.39
            assert data['available_sol'] == 0.13
            assert data['unit'] == 'SOL'
            assert data['approximate'] is True
            assert response.headers['Cache-Control'] == 'private, no-store'
            snapshot.assert_called_once_with(
                snapshot.call_args.args[0], 'user-one')
    finally:
        temp.cleanup()




def test_zero_real_sol_can_coexist_with_other_token_portfolio_value():
    temp, client, viewer = setup()
    try:
        from types import SimpleNamespace
        # Exactly the distinction shown in the user's screenshot. No
        # spendable SOL, but other wallet assets have market value.
        with patch('portfolio_multichain_holdings._portfolio_snapshot',
                   return_value={
                       'total_sol': 0.106,
                       'available_to_trade_sol': 0.0,
                       'stable': {'solana_sol': 0.0, 'evm_chains': {}},
                       'generated_at': 1780000000.0,
                       'stale': False
                   }):
            response = client.get('/api/profile/1/portfolio-balance')
            assert response.status_code == 200
            assert response.json['portfolio_value_sol_approx'] == 0.106
            assert response.json['available_sol'] == 0.0
            assert response.json['other_assets_sol_approx'] == 0.106
            assert response.json['generated_at'] == 1780000000.0
    finally:
        temp.cleanup()


def test_profile_available_sol_is_solana_only():
    temp, client, viewer = setup()
    try:
        # Legacy snapshot fields may still exist in historical fixtures, but
        # the active profile balance must only expose Solana SOL.
        with patch('portfolio_multichain_holdings._portfolio_snapshot',
                   return_value={
                       'total_sol': 1.6,
                       'available_to_trade_sol': 0.5,
                       'stable': {
                           'solana_sol': 0.5,
                           'evm_chains': {'legacy': 1.1}
                       }, 'stale': False,
                   }):
            response = client.get('/api/profile/1/portfolio-balance')
            assert response.status_code == 200
            assert response.json['portfolio_value_sol_approx'] == 1.6
            assert response.json['available_sol'] == 0.5
            assert response.json['other_assets_sol_approx'] == 1.1
    finally:
        temp.cleanup()



def test_private_profile_never_exposes_other_user_balance():
    temp, client, viewer = setup()
    try:
        with patch('portfolio_multichain_holdings._portfolio_snapshot') as snapshot:
            response = client.get('/api/profile/2/portfolio-balance')
            assert response.status_code == 403
            assert snapshot.call_count == 0
            viewer[0] = 'user-two'
            snapshot.return_value = {'total_sol': 3,
                                     'available_to_trade_sol': 2,
                                     'stable': {'solana_sol': 2, 'evm_chains': {}},
                                     'stale': True}
            response = client.get('/api/profile/2/portfolio-balance')
            assert response.status_code == 200
            assert response.json['stale'] is True
    finally:
        temp.cleanup()


def test_public_profile_uses_fast_direct_sol_without_indexed_snapshot():
    temp, client, viewer = setup()
    try:
        viewer[0] = 'some-other-viewer'
        app = client.application
        endpoint = next(k for k in app.view_functions if k.endswith('profile_portfolio_balance'))
        view = app.view_functions[endpoint]
        d = next(c.cell_contents for c in view.__closure__
                 if hasattr(c.cell_contents, '_get_user_sol'))
        d._get_trading_wallet_address = lambda wallet: 'profile-trading-wallet'
        d._get_user_sol = lambda wallet: 4.2
        with patch('portfolio_multichain_holdings._portfolio_snapshot') as snapshot:
            response = client.get('/api/profile/1/portfolio-balance')
            assert response.status_code == 200
            assert response.json['available_sol'] == 4.195
            assert response.json['portfolio_value_sol_approx'] == 4.2
            assert response.json['partial'] is True
            assert snapshot.call_count == 0
    finally:
        temp.cleanup()


def test_snapshot_indexer_outage_still_returns_live_profile_sol():
    temp, client, viewer = setup()
    try:
        app = client.application
        # Reconfigure the installed route's backing dashboard namespace via the
        # closure object used by the module install test helper.
        endpoint = next(k for k in app.view_functions if k.endswith('profile_portfolio_balance'))
        view = app.view_functions[endpoint]
        # rate_limit is a no-op in this fixture, so the dashboard namespace is
        # the first closure cell containing the expected direct balance helper.
        d = next(c.cell_contents for c in view.__closure__
                 if hasattr(c.cell_contents, '_get_user_sol'))
        d._get_trading_wallet_address = lambda wallet: 'trading-wallet'
        d._get_user_sol = lambda wallet: 12.345678
        with patch('portfolio_multichain_holdings._portfolio_snapshot',
                   side_effect=RuntimeError('indexed provider down')):
            response = client.get('/api/profile/1/portfolio-balance')
            assert response.status_code == 200
            data = response.json
            assert data['ok'] is True
            assert data['partial'] is True
            assert data['scope'] == 'solana_sol'
            assert data['portfolio_value_sol_approx'] == 12.345678
            assert abs(data['available_sol'] - 12.340678) < 1e-9
            assert data['other_assets_sol_approx'] is None
            assert data['approximate'] is False
    finally:
        temp.cleanup()


def test_rpc_failure_or_bad_snapshot_is_not_false_zero():
    temp, client, viewer = setup()
    try:
        with patch('portfolio_multichain_holdings._portfolio_snapshot',
                   side_effect=RuntimeError('provider down')):
            response = client.get('/api/profile/1/portfolio-balance')
            assert response.status_code == 503
            assert 'portfolio_value_sol_approx' not in response.json
        with patch('portfolio_multichain_holdings._portfolio_snapshot',
                   return_value={'total_sol': None,
                                 'available_to_trade_sol': 2}):
            response = client.get('/api/profile/1/portfolio-balance')
            assert response.status_code == 503
    finally:
        temp.cleanup()


def test_missing_user_does_not_trigger_portfolio_rpc():
    temp, client, viewer = setup()
    try:
        with patch('portfolio_multichain_holdings._portfolio_snapshot') as snapshot:
            response = client.get('/api/profile/9876/portfolio-balance')
            assert response.status_code == 404
            assert snapshot.call_count == 0
    finally:
        temp.cleanup()


def test_display_uses_named_profile_id_and_privacy_template_flag():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    profile = (root / 'templates/profile.html').read_text()
    script = (root / 'static/tip-experience.js').read_text()
    styles = (root / 'static/tip-experience.css').read_text()
    assert '{% if can_view_sensitive|default(false) %}' in profile
    assert 'id="oa-profile-balance"' in profile
    assert 'data-user-id="{{ user_id }}"' in profile
    assert '/api/profile/' in script and '/portfolio-balance' in script
    assert 'portfolio_value_sol_approx' in script
    assert 'available_sol' in script
    assert 'oa-profile-balance-other' in profile
    assert 'Available SOL balance' in profile
    assert 'Other assets · estimated SOL equivalent' in profile
    assert 'oa-profile-balance-chain">Solana<' in profile
    assert 'id="oa-profile-balance-unit"' in profile
    assert "Live Solana SOL balance" in script
    assert "partial=!!d.partial" in script
    assert 'other_assets_sol_approx' in script
    assert '15000' in script
    assert 'visibilitychange' in script
    assert '15000' in script
    assert 'oa-profile-balance-state' not in profile
    assert 'oa-profile-balance-state' not in script
    assert 'oa-profile-balance-state' not in styles
    assert "textContent='Unavailable'" in script
    assert '.oa-profile-balance-value' in styles


if __name__ == '__main__':
    for name in sorted(key for key in globals() if key.startswith('test_')):
        globals()[name]()
        print('PASS', name)
    print('ALL PROFILE PORTFOLIO BALANCE REGRESSIONS PASSED')
