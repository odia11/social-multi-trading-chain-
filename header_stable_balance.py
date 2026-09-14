"""Shared navbar stablecoin balance.

The compact amount pill in OrcAgent's top bar used to show the Solana/native
balance returned by /api/me.  The product now treats stablecoins as the user's
spending balance, so this exposes one read-only aggregate across supported
chains and injects a tiny shared client that keeps the pill fresh.

Display policy: show one dollar figure (e.g. $124.58).  Under the hood this is
USDC on Solana/BSC/Base/Arbitrum/Polygon and the configured stable asset on
Robinhood Chain (currently USDG).  No conversion, transfer or bridge is
performed here; this endpoint only reads on-chain balances.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

_CACHE = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 12.0
_CHAINS = ('bsc', 'base', 'arbitrum', 'polygon', 'robinhood')


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

    def _wallet_row(wallet):
        conn = sqlite3.connect(d.DB_FILE)
        try:
            return conn.execute(
                'SELECT id, bsc_wallet_address FROM users WHERE wallet_address=?',
                (wallet,),
            ).fetchone()
        finally:
            conn.close()

    def _read_total(wallet):
        row = _wallet_row(wallet)
        evm_address = str(row[1] or '').strip() if row else ''
        try:
            sol_address = d._get_trading_wallet_address(wallet) or ''
        except Exception:
            sol_address = ''

        balances = {'solana': 0.0, 'bsc': 0.0, 'base': 0.0,
                    'arbitrum': 0.0, 'polygon': 0.0, 'robinhood': 0.0}
        errors = []

        jobs = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            if sol_address:
                jobs[pool.submit(d._get_solana_usdc_balance, sol_address)] = 'solana'
            if evm_address:
                for chain in _CHAINS:
                    jobs[pool.submit(d.get_evm_usdc_balance, evm_address, chain)] = chain

            for future in as_completed(jobs):
                chain = jobs[future]
                try:
                    balances[chain] = _safe_float(future.result())
                except Exception as exc:
                    errors.append(chain)
                    app.logger.debug('navbar stable balance read failed on %s: %s', chain, exc)

        total = round(sum(balances.values()), 6)
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
