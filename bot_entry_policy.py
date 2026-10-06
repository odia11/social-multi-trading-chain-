"""Hard entry policy and per-user bot status truth.

Product invariants:
- autonomous entries never open below a +7% observed price move;
- fast-pump detection uses the same +7% floor;
- bot UI/status responses are refreshed from the authenticated user's own
  settings/state instead of relying on stale/default client values.

The core trader still owns all safety checks and execution.  This module only
adds the hard entry floor and refreshes response fields that describe the
current user's bot.
"""

import json
import math
import sqlite3

ENTRY_TRIGGER_PCT = 7.0
_STATUS_PATHS = {'/api/bot/overview', '/api/bot/status'}
_MOVE_FIELDS = (
    'change5m', 'change15m', 'change1h',
    'price_change_5m', 'price_change_15m', 'price_change_1h',
)


def _observed_move_pct(token):
    """Largest positive move in a detailed token snapshot, or None if absent."""
    if not isinstance(token, dict):
        return None
    seen = []
    for key in _MOVE_FIELDS:
        if key not in token:
            continue
        try:
            value = float(token.get(key))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            seen.append(value)
    return max(seen) if seen else None


def _fresh_user_bot_fields(d, wallet):
    fields = {}
    try:
        with sqlite3.connect(d.DB_FILE, timeout=3) as conn:
            cols = {row[1] for row in conn.execute('PRAGMA table_info(users)').fetchall()}
            wanted = [
                c for c in (
                    'take_profit', 'stop_loss', 'min_trade_size',
                    'max_trade_size', 'max_positions', 'daily_loss_limit',
                ) if c in cols
            ]
            if wanted:
                row = conn.execute(
                    'SELECT ' + ','.join(wanted) + ' FROM users WHERE wallet_address=?',
                    (wallet,),
                ).fetchone()
                if row:
                    fields.update(dict(zip(wanted, row)))
    except (sqlite3.Error, TypeError, ValueError):
        pass

    try:
        state = d.get_user_state(wallet) or {}
    except Exception:
        state = {}
    fields['running'] = bool(state.get('trader_running'))

    try:
        positions = d._fetch_open_bot_positions(wallet)
        fields['open_positions'] = len(positions or [])
    except Exception:
        try:
            positions = state.get('positions') or {}
            fields['open_positions'] = sum(
                1 for p in positions.values()
                if isinstance(p, dict)
                and p.get('amount', 0)
                and p.get('source', 'bot') == 'bot'
            )
        except Exception:
            pass

    fields['entry_trigger_pct'] = ENTRY_TRIGGER_PCT
    return fields


def install(d):
    if getattr(d, '_bot_entry_policy_installed', False):
        return
    d._bot_entry_policy_installed = True
    d.BOT_ENTRY_TRIGGER_PCT = ENTRY_TRIGGER_PCT

    # The first scanner pass sometimes has only transaction/liquidity fields.
    # Keep that discovery pass intact.  The later detailed token snapshot has
    # change5m/change1h and is checked through the same helper; that is where
    # the hard +7% gate applies immediately before entry safety/execution.
    original_eligible = getattr(d, '_bot_gainers_eligible', None)
    if not callable(original_eligible):
        raise RuntimeError('bot eligibility function unavailable')

    def eligible(token):
        if not original_eligible(token):
            return False
        move = _observed_move_pct(token)
        if move is None:
            return True
        return move >= ENTRY_TRIGGER_PCT

    d._bot_gainers_eligible = eligible

    # Existing fast-pump path used 6%/15s.  It is an alternate entry route,
    # so it must obey the same hard floor and may never bypass +7%.
    if hasattr(d, 'FAST_PUMP_THRESHOLD'):
        d.FAST_PUMP_THRESHOLD = ENTRY_TRIGGER_PCT / 100.0

    app = d.app

    @app.after_request
    def _bot_status_truth(response):
        try:
            from flask import request
            if request.path not in _STATUS_PATHS or not response.is_json:
                return response
            wallet = d._authenticated_wallet()
            if not wallet:
                return response
            data = response.get_json(silent=True)
            if not isinstance(data, dict) or not data.get('ok', True):
                return response
            data.update(_fresh_user_bot_fields(d, wallet))
            response.set_data(json.dumps(data, separators=(',', ':'), ensure_ascii=False))
            response.headers['Cache-Control'] = 'no-store, private'
            response.headers['Pragma'] = 'no-cache'
        except Exception:
            # Status decoration must never turn a valid page/API response into
            # a 500; the base bot endpoint remains the fallback.
            pass
        return response
