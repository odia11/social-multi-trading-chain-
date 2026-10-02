"""Shared navbar stablecoin balance.

The compact amount pill shows the user's spendable Solana USDC balance.
OrcAgent is Solana-only; no EVM balance is queried or included.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

_CACHE = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 12.0
_CHAINS = ()


def _safe_float(value):
    try:
        value = float(value or 0)
        return value if value >= 0 else 0.0
    except Exception:
        return 0.0


def install(d):
    if getattr(d, '_orca_header_stable_balance_installed', False):
        return
    d._orca_header_stable_balance_installed = True
    app = d.app

    def _read_total(wallet):
        try:
            sol_address = d._get_trading_wallet_address(wallet) or ''
        except Exception:
            sol_address = ''

        balances = {'solana': 0.0}
        errors = []
        if sol_address:
            try:
                balances['solana'] = _safe_float(d._get_solana_usdc_balance(sol_address))
            except Exception as exc:
                errors.append('solana')
                app.logger.debug('navbar stable balance read failed on solana: %s', exc)

        total = round(balances['solana'], 6)
        return total, balances, errors

    @app.route('/api/header/stable-balance', methods=['GET'])
    def header_stable_balance():
        wallet = d._authenticated_wallet()
        if not wallet:
            return d.jsonify({'ok': False, 'total_usd': 0.0,
                              'formatted': '$0.00', 'authenticated': False}), 401

        now = time.time()
        with _CACHE_LOCK:
            cached = _CACHE.get(wallet)
            if cached and now - cached['ts'] < _CACHE_TTL:
                return d.jsonify(cached['body'])

        total, balances, errors = _read_total(wallet)
        body = {
            'ok': True,
            'authenticated': True,
            'total_usd': total,
            'formatted': '${:,.2f}'.format(total),
            'balances': {k: round(v, 6) for k, v in balances.items()},
            'complete': not errors,
            'unavailable_chains': errors,
        }
        with _CACHE_LOCK:
            _CACHE[wallet] = {'ts': now, 'body': body}
        return d.jsonify(body)

    marker = 'data-orca-stable-balance="1"'

    @app.after_request
    def _inject_header_stable_balance(response):
        try:
            if response.status_code != 200 or response.mimetype != 'text/html':
                return response
            body = response.get_data(as_text=True)
            if marker in body or 'pt-nb-sol-balance' not in body:
                return response
            version = getattr(d, '_APP_VERSION', '1')
            tag = ('<script src="/static/header-stable-balance.js?v=%s" defer %s></script>'
                   % (version, marker))
            body = body.replace('</body>', tag + '</body>', 1) if '</body>' in body else body + tag
            response.set_data(body)
            response.content_length = len(response.get_data())
        except Exception as exc:
            app.logger.debug('stable-balance navbar injection skipped: %s', exc)
        return response
