"""Regression tests for the hard +7% autonomous-entry rule and per-user bot truth."""

import os
import sqlite3
import tempfile
from types import SimpleNamespace

from flask import Flask, jsonify

import bot_entry_policy as policy


def _fake_dashboard(db_path):
    app = Flask(__name__)
    app.secret_key = 'test'
    wallet = 'wallet-1'
    state = {
        'trader_running': True,
        'positions': {
            'A': {'amount': 1, 'source': 'bot'},
            'B': {'amount': 1, 'source': 'manual'},
        },
    }
    d = SimpleNamespace(
        app=app,
        DB_FILE=db_path,
        FAST_PUMP_THRESHOLD=.06,
        _bot_gainers_eligible=lambda t: (t.get('txns24h') or 0) >= 100,
        _authenticated_wallet=lambda: wallet,
        get_user_state=lambda w: state,
        _fetch_open_bot_positions=lambda w: [{'mint': 'A'}, {'mint': 'C'}],
    )

    @app.get('/api/bot/overview')
    def overview():
        return jsonify({
            'ok': True,
            'running': False,
            'take_profit': 999,
            'stop_loss': 999,
            'max_positions': 99,
            'open_positions': 99,
        })

    @app.get('/api/bot/status')
    def status():
        return jsonify({'ok': True, 'running': False, 'open_positions': 99})

    return d, wallet


def test_hard_seven_percent_floor_and_user_truth():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    try:
        with sqlite3.connect(path) as conn:
            conn.execute(
                '''CREATE TABLE users (
                    wallet_address TEXT PRIMARY KEY,
                    take_profit REAL,
                    stop_loss REAL,
                    min_trade_size REAL,
                    max_trade_size REAL,
                    max_positions INTEGER,
                    daily_loss_limit REAL
                )'''
            )
            conn.execute(
                'INSERT INTO users VALUES (?,?,?,?,?,?,?)',
                ('wallet-1', 22.5, 8.5, 3.0, 12.0, 4, 30.0),
            )
            conn.commit()

        d, _ = _fake_dashboard(path)
        original = d._bot_gainers_eligible
        policy.install(d)

        # Discovery snapshots may not have movement fields yet; keep the
        # existing market-activity gate until the detailed token snapshot.
        assert d._bot_gainers_eligible({'txns24h': 100})
        assert not d._bot_gainers_eligible({'txns24h': 99})

        # The detailed pre-entry snapshot is the hard gate.
        assert not d._bot_gainers_eligible({'txns24h': 100, 'change5m': 6.99, 'change1h': 6.5})
        assert d._bot_gainers_eligible({'txns24h': 100, 'change5m': 7.0, 'change1h': 1.0})
        assert d._bot_gainers_eligible({'txns24h': 100, 'change5m': -1.0, 'change1h': 8.0})
        assert d.FAST_PUMP_THRESHOLD == .07
        assert original is not d._bot_gainers_eligible

        client = d.app.test_client()
        ov = client.get('/api/bot/overview').get_json()
        assert ov['running'] is True
        assert ov['take_profit'] == 22.5
        assert ov['stop_loss'] == 8.5
        assert ov['min_trade_size'] == 3.0
        assert ov['max_trade_size'] == 12.0
        assert ov['max_positions'] == 4
        assert ov['daily_loss_limit'] == 30.0
        assert ov['open_positions'] == 2
        assert ov['entry_trigger_pct'] == 7.0

        st = client.get('/api/bot/status').get_json()
        assert st['running'] is True
        assert st['open_positions'] == 2
        assert st['max_positions'] == 4
        assert st['entry_trigger_pct'] == 7.0
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_production_entry_and_ui_use_policy():
    root = os.path.dirname(os.path.dirname(__file__))
    entry = open(os.path.join(root, 'app_entry.py'), encoding='utf-8').read()
    dashboard = open(os.path.join(root, 'dashboard.py'), encoding='utf-8').read()
    bot = open(os.path.join(root, 'templates', 'auto_trading_bot.html'), encoding='utf-8').read()
    home = open(os.path.join(root, 'static', 'home-mobile.js'), encoding='utf-8').read()

    assert 'from bot_entry_policy import install as _install_bot_entry_policy' in entry
    assert '_install_bot_entry_policy(_dashboard)' in entry
    assert '_bot_gainers_eligible(_td)' in dashboard, 'detailed pre-entry token snapshot must pass the hard entry policy'
    assert 'id="strategy-entry"' in bot
    assert "r.entry_trigger_pct||7" in bot
    assert "open+'/'+(max&&Number.isFinite(max)?max:'—')+' open trades'" in home
    assert "open+'/5 open trades'" not in home
    assert "USDC capital" in home
