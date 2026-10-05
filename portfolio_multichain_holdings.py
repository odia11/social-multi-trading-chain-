"""Authoritative Solana Portfolio snapshot.

OrcAgent is Solana-only. Legacy EVM database columns/rows are intentionally
left untouched for historical recovery, but they are never queried into the
active Portfolio snapshot.
"""
from __future__ import annotations

import sqlite3
import math
import threading
import time


def _num(v, default=0.0):
    try:
        result = float(v if v is not None else default)
        return result if math.isfinite(result) else float(default)
    except Exception:
        return float(default)


_SNAPSHOT_CACHE = {}
_SNAPSHOT_LOCK = threading.Lock()
_SNAPSHOT_TTL = 5.0
_SNAPSHOT_FLIGHTS = {}


def _merge_evm_positions(d, wallet, tokens):
    """Legacy name kept for call-site compatibility; only Solana assets pass."""
    return [dict(t) for t in (tokens or [])]


def _portfolio_snapshot(d, wallet, bust=False):
    owner = d._get_trading_wallet_address(wallet) or wallet
    key = (d.DB_FILE, wallet, owner)
    with _SNAPSHOT_LOCK:
        lock = _SNAPSHOT_FLIGHTS.setdefault(key, threading.Lock())
    with lock:
        now = time.time()
        previous = _SNAPSHOT_CACHE.get(key)
        if not bust and previous and now - previous['generated_at'] < _SNAPSHOT_TTL:
            return previous
        if bust:
            d._wallet_tokens_cache.pop(wallet, None)
        try:
            token_data = d._fetch_wallet_tokens(wallet, owner)
        except Exception:
            if previous:
                return dict(previous, stale=True, partial=True, unavailable=['full_token_index'])
            raise RuntimeError('complete portfolio snapshot unavailable')
        inventory_complete = bool(token_data.get('inventory_complete', True))
        if not inventory_complete and previous:
            return dict(previous, stale=True, partial=True, unavailable=['full_token_index'])
        assets = [dict(t) for t in token_data.get('tokens', [])]
        sol_mint = getattr(d, 'SOL_MINT', 'So11111111111111111111111111111111111111112')
        usdc_mint = getattr(d, 'USDC_MINT', 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v')
        sol_row = next((t for t in assets if t.get('is_native')), None) or next(
            (t for t in assets if t.get('mint') == sol_mint and t.get('is_native') is not False), None)
        if sol_row is None:
            raise RuntimeError('native SOL balance missing from inventory')
        for t in assets:
            t['chain'] = 'solana'
            t['usd_value'] = _num(t.get('value_usd', t.get('usd_value')))
        sol_amount = _num(sol_row.get('amount'))
        sol_price = _num(sol_row.get('price_usd')) or _num(d._sol_price_usd)
        sol_value = sol_amount * sol_price
        sol_row.update(price_usd=sol_price,value_usd=sol_value,usd_value=sol_value)
        # Exact mint identity, not ticker: a fake $USDC or $SOL must never
        # replace the pinned canonical asset or disappear from the totals.
        stable_total = sum(_num(t.get('amount')) for t in assets if t.get('mint') == usdc_mint)
        other_value = sum(t['usd_value'] for t in assets if t.get('mint') != usdc_mint and t is not sol_row)
        unpriced = [t['mint'] for t in assets if _num(t.get('amount')) > 0
                    and _num(t.get('price_usd')) <= 0]
        valuation_complete = bool(token_data.get('valuation_complete', True)) and not unpriced
        total = stable_total + sol_value + other_value
        in_positions_sol = 0.0
        try:
            with sqlite3.connect(d.DB_FILE, timeout=3) as c:
                uid = c.execute('SELECT id FROM users WHERE wallet_address=?',(wallet,)).fetchone()
                if uid:
                    row = c.execute("SELECT COALESCE(SUM(spend),0) FROM open_positions "
                        "WHERE user_id=? AND COALESCE(chain,'solana')='solana' "
                        "AND COALESCE(base_currency,'SOL')='SOL'",(uid[0],)).fetchone()
                    in_positions_sol = _num(row[0])
        except sqlite3.Error:
            pass
        snapshot = dict(ok=True,generated_at=token_data.get('ts', now),
            wallets={'solana':owner},total_usd=round(total,4),
            available_to_trade_usdc=round(stable_total,4),trading_currency='SOL',
            available_to_trade_sol=max(0,sol_amount-d.SOL_NETWORK_RESERVE),
            total_sol=total/sol_price if sol_price>0 else None,
            stable=dict(total_usdc=round(stable_total,4),solana_usdc=round(stable_total,4),evm_chains={}),
            sol=dict(amount=sol_amount,price_usd=sol_price,value_usd=sol_value,in_positions_sol=in_positions_sol),
            other_assets_value_usd=round(other_value,4),assets=assets,asset_count=len(assets),
            inventory_complete=inventory_complete,valuation_complete=valuation_complete,
            unpriced_mints=unpriced,stale_price_mints=token_data.get('stale_price_mints',[]),
            partial=not inventory_complete,stale=bool(token_data.get('stale')),
            unavailable=token_data.get('unavailable',[]))
        if inventory_complete and not snapshot['stale']:
            _SNAPSHOT_CACHE[key] = snapshot
        return snapshot


def install(d):
    if getattr(d, '_orca_multichain_portfolio_installed', False):
        return
    d._orca_multichain_portfolio_installed = True
    app = d.app

    endpoint = None
    for rule in app.url_map.iter_rules():
        if rule.rule == '/api/wallet/tokens' and 'GET' in rule.methods:
            endpoint = rule.endpoint
            break
    if not endpoint or endpoint not in app.view_functions:
        app.logger.warning('multichain portfolio: /api/wallet/tokens not found')
        return

    original = app.view_functions[endpoint]

    def multichain_wallet_tokens(*args, **kwargs):
        response = app.make_response(original(*args, **kwargs))
        if response.status_code != 200:
            return response
        try:
            body = response.get_json(silent=True) or {}
            tokens = list(body.get('tokens') or [])
            wallet = d._authenticated_wallet()
            if not wallet:
                return response

            tokens = _merge_evm_positions(d, wallet, tokens)
            body['tokens'] = tokens
            body['ok'] = body.get('ok', True)
            body['multichain'] = True
            response = d.jsonify(body)
        except Exception as exc:
            app.logger.warning('multichain portfolio merge failed: %s', exc)
        return response

    app.view_functions[endpoint] = multichain_wallet_tokens

    @app.get('/api/portfolio/snapshot')
    def portfolio_snapshot():
        wallet = d._authenticated_wallet()
        if not wallet:
            return d.jsonify({'ok': False, 'msg': 'No wallet connected'}), 401
        try:
            snap = _portfolio_snapshot(d, wallet, bust=d.request.args.get('bust') == '1')
            return d.jsonify(snap)
        except Exception as exc:
            app.logger.warning('portfolio snapshot failed: %s', str(exc)[:240])
            return d.jsonify({'ok': False, 'msg': 'Portfolio snapshot temporarily unavailable'}), 503

    marker = 'data-orca-portfolio-multichain="1"'

    @app.after_request
    def _inject_multichain_portfolio_ui(response):
        try:
            if response.status_code != 200 or response.mimetype != 'text/html':
                return response
            if (d.request.path.rstrip('/') or '/') != '/wallet':
                return response
            html = response.get_data(as_text=True)
            if marker in html:
                return response
            version = getattr(d, '_APP_VERSION', '1')
            # pf-stable-2 is intentional: iOS/PWA can hold a previous controller
            # even after deploy when the app version itself does not change.
            tag = '<script src="/static/portfolio-multichain.js?v=%s-pf-stable-2" defer %s></script>' % (version, marker)
            html = html.replace('</body>', tag + '</body>', 1) if '</body>' in html else html + tag
            response.set_data(html)
            response.content_length = len(response.get_data())
        except Exception as exc:
            app.logger.debug('multichain portfolio UI injection skipped: %s', exc)
        return response
