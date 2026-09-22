"""Profile portfolio USDC display: role scoped and never a fake zero.

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
    )
    mod.install(d)
    return tmp, app.test_client(), viewer


def test_public_balance_is_for_profile_user_not_viewer():
    temp, client, viewer = setup()
    try:
        with patch('portfolio_multichain_holdings._portfolio_snapshot',
                   return_value={'total_usd': 1.39,
                                 'available_to_trade_usdc': 0.13,
                                 'stale': False}) as snapshot:
            response = client.get('/api/profile/1/portfolio-balance')
            assert response.status_code == 200
            data = response.json
            assert data['ok'] is True
            assert data['portfolio_value_usdc_approx'] == 1.39
            assert data['available_usdc'] == 0.13
            assert data['unit'] == 'USDC'
            assert data['approximate'] is True
            assert response.headers['Cache-Control'] == 'private, no-store'
            snapshot.assert_called_once_with(
                snapshot.call_args.args[0], 'user-one')
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
            snapshot.return_value = {'total_usd': 3,
                                     'available_to_trade_usdc': 2,
                                     'stale': True}
            response = client.get('/api/profile/2/portfolio-balance')
            assert response.status_code == 200
            assert response.json['stale'] is True
    finally:
        temp.cleanup()


def test_rpc_failure_or_bad_snapshot_is_not_false_zero():
    temp, client, viewer = setup()
    try:
        with patch('portfolio_multichain_holdings._portfolio_snapshot',
                   side_effect=RuntimeError('provider down')):
            response = client.get('/api/profile/1/portfolio-balance')
            assert response.status_code == 503
            assert 'portfolio_value_usdc_approx' not in response.json
        with patch('portfolio_multichain_holdings._portfolio_snapshot',
                   return_value={'total_usd': None,
                                 'available_to_trade_usdc': 2}):
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
    assert 'portfolio_value_usdc_approx' in script
    assert 'available_usdc' in script
    assert "textContent='Unavailable'" in script
    assert '.oa-profile-balance-value' in styles


if __name__ == '__main__':
    for name in sorted(key for key in globals() if key.startswith('test_')):
        globals()[name]()
        print('PASS', name)
    print('ALL PROFILE PORTFOLIO BALANCE REGRESSIONS PASSED')
