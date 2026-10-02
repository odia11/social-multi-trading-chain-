"""Authoritative Solana Portfolio snapshot.

OrcAgent is Solana-only. Legacy EVM database columns/rows are intentionally
left untouched for historical recovery, but they are never queried into the
active Portfolio snapshot.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


def _num(v, default=0.0):
    try:
        return float(v if v is not None else default)
    except Exception:
        return float(default)


_SNAPSHOT_CACHE = {}
_SNAPSHOT_LOCK = threading.Lock()
_SNAPSHOT_TTL = 4.0


def _merge_evm_positions(d, wallet, tokens):
    """Legacy name kept for call-site compatibility; only Solana assets pass."""
    return [dict(t) for t in (tokens or [])]


def _portfolio_snapshot(d, wallet, bust=False):
    now = time.time()
    if not bust:
        with _SNAPSHOT_LOCK:
            cached = _SNAPSHOT_CACHE.get(wallet)
            if cached and now - cached[0] < _SNAPSHOT_TTL:
                return cached[1]

    onchain_wallet = d._get_trading_wallet_address(wallet) or wallet

    if bust:
        try:
            d._wallet_tokens_cache.pop(wallet, None)
        except Exception:
            pass

    # Token holdings and stablecoin balances are independent reads. Execute
    # them concurrently and publish only one completed snapshot to the UI.
    jobs = {'tokens': lambda: d._fetch_wallet_tokens(wallet, onchain_wallet),
            'solana_usdc': lambda: d._get_solana_usdc_balance(onchain_wallet)}

    results = {}
    errors = {}
    with ThreadPoolExecutor(max_workers=max(2, len(jobs))) as ex:
        future_map = {ex.submit(fn): name for name, fn in jobs.items()}
        for fut in as_completed(future_map):
            name = future_map[fut]
            try:
                results[name] = fut.result()
            except Exception as exc:
                errors[name] = type(exc).__name__

    # Never publish a mathematically incomplete total. If one independent
    # chain/RPC fails, keep the last complete snapshot rather than making a
    # user's balance visibly drop and jump back on the next poll.
    if errors:
        with _SNAPSHOT_LOCK:
            previous = _SNAPSHOT_CACHE.get(wallet)
        if previous:
            stale = dict(previous[1])
            stale['stale'] = True
            stale['partial'] = False
            stale['unavailable'] = sorted(errors.keys())
            return stale
        raise RuntimeError('portfolio snapshot incomplete: ' + ','.join(sorted(errors.keys())))

    token_data = results.get('tokens') or {'tokens': []}
    assets = _merge_evm_positions(d, wallet, token_data.get('tokens') or [])
    for t in assets:
        if 'usd_value' not in t:
            t['usd_value'] = _num(t.get('value_usd'))
        if 'chain' not in t:
            t['chain'] = 'solana'

    solana_usdc = _num(results.get('solana_usdc'))
    evm_chains = {}
    stable_total = solana_usdc

    sol_row = next((t for t in assets if str(t.get('symbol') or '').upper() == 'SOL'
                    and str(t.get('chain') or 'solana') == 'solana'), None)
    sol_amount = _num(sol_row.get('amount')) if sol_row else 0.0
    sol_price = _num(sol_row.get('price_usd')) if sol_row else _num(getattr(d, '_sol_price_usd', 0))
    sol_value = _num(sol_row.get('usd_value', sol_row.get('value_usd'))) if sol_row else sol_amount * sol_price

    stable_symbols = {'USDC', 'USDT', 'USDG'}
    other_value = 0.0
    for t in assets:
        sym = str(t.get('symbol') or '').upper()
        if sym == 'SOL' or sym in stable_symbols:
            continue
        other_value += _num(t.get('usd_value', t.get('value_usd')))

    total = stable_total + sol_value + other_value

    in_positions_sol = 0.0
    try:
        conn = sqlite3.connect(d.DB_FILE, timeout=8.0)
        uid_row = conn.execute('SELECT id FROM users WHERE wallet_address=?', (wallet,)).fetchone()
        if uid_row:
            spent = conn.execute(
                "SELECT COALESCE(SUM(spend),0) FROM open_positions "
                "WHERE user_id=? AND COALESCE(chain,'solana')='solana'",
                (uid_row[0],)).fetchone()
            in_positions_sol = _num(spent[0] if spent else 0)
        conn.close()
    except Exception:
        pass

    snapshot = {
        'ok': True,
        'generated_at': now,
        'wallets': {'solana': onchain_wallet},
        'total_usd': round(total, 4),
        'available_to_trade_usdc': round(stable_total, 4),
        'stable': {
            'total_usdc': round(stable_total, 4),
            'solana_usdc': round(solana_usdc, 4),
            'evm_chains': {k: round(v, 4) for k, v in evm_chains.items()},
        },
        'sol': {
            'amount': round(sol_amount, 8), 'price_usd': round(sol_price, 6),
            'value_usd': round(sol_value, 4),
            'in_positions_sol': round(in_positions_sol, 8),
        },
        'other_assets_value_usd': round(other_value, 4),
        'assets': assets,
        'asset_count': len(assets),
        'partial': False,
        'stale': False,
        'unavailable': [],
    }
    with _SNAPSHOT_LOCK:
        _SNAPSHOT_CACHE[wallet] = (now, snapshot)
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
