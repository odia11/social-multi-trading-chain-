"""Add every supported-chain open position to the Portfolio token feed.

The legacy /api/wallet/tokens endpoint is Solana/SPL-oriented. OrcAgent now
trades BSC, Base, Arbitrum, Polygon and Robinhood Chain too, so successful EVM
positions must not disappear from Portfolio just because they are not SPL
accounts. This adapter keeps the existing endpoint and appends the user's
recorded non-Solana open positions in the same shape the wallet UI already
renders.

No trading logic is changed here. It is a read-only presentation adapter.
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
    """Append durable EVM open positions to the SPL token snapshot."""
    out = [dict(t) for t in (tokens or [])]
    seen = set()
    for t in out:
        addr = str(t.get('mint') or t.get('address') or t.get('token_address') or '').lower()
        chain = str(t.get('chain') or 'solana').lower()
        if addr:
            seen.add((chain, addr))

    try:
        conn = sqlite3.connect(d.DB_FILE, timeout=8.0)
        uid_row = conn.execute('SELECT id FROM users WHERE wallet_address=?', (wallet,)).fetchone()
        rows = []
        if uid_row:
            rows = conn.execute(
                "SELECT mint_address,symbol,amount,buy_price,spend,chain,opened_at "
                "FROM open_positions WHERE user_id=? AND COALESCE(chain,'solana')!='solana' AND amount>0",
                (uid_row[0],)).fetchall()
        conn.close()
    except Exception:
        rows = []

    supported = set(getattr(d, 'EVM_CHAINS', {}).keys())
    for address, symbol, amount, buy_price, spend, chain, opened_at in rows:
        chain = str(chain or '').lower()
        token_address = str(address or '').strip()
        if chain not in supported or not token_address or (chain, token_address.lower()) in seen:
            continue
        amount = _num(amount)
        if amount <= 0:
            continue
        symbol = str(symbol or token_address[:8]).replace('$', '')
        price = 0.0
        name = symbol
        logo = ''
        change24 = 0.0
        try:
            td = d.get_token_data(token_address, chain=chain)
            if td:
                symbol = str(td.get('symbol') or symbol).replace('$', '')
                name = str(td.get('name') or name)
                price = _num(td.get('price', td.get('price_usd', 0)))
                logo = str(td.get('logo_url') or td.get('image') or '')
                change24 = _num(td.get('change24h', td.get('price_change_24h', 0)))
        except Exception:
            pass
        value = amount * price if price > 0 else _num(spend)
        out.append({
            'mint': token_address, 'address': token_address,
            'token_address': token_address, 'symbol': symbol, 'name': name,
            'amount': amount, 'price_usd': price,
            'usd_value': value, 'value_usd': value,
            'avg_price': _num(buy_price), 'price_change_24h': change24,
            'logo_url': logo, 'chain': chain, 'is_evm': True,
            'opened_at': opened_at,
        })
        seen.add((chain, token_address.lower()))
    return out


def _portfolio_snapshot(d, wallet, bust=False):
    now = time.time()
    if not bust:
        with _SNAPSHOT_LOCK:
            cached = _SNAPSHOT_CACHE.get(wallet)
            if cached and now - cached[0] < _SNAPSHOT_TTL:
                return cached[1]

    onchain_wallet = d._get_trading_wallet_address(wallet) or wallet
    evm_address = ''
    try:
        conn = sqlite3.connect(d.DB_FILE, timeout=8.0)
        row = conn.execute(
            'SELECT id,COALESCE(bsc_wallet_address,"") FROM users WHERE wallet_address=?',
            (wallet,)).fetchone()
        conn.close()
        if row:
            evm_address = str(row[1] or '')
    except Exception:
        pass

    if bust:
        try:
            d._wallet_tokens_cache.pop(wallet, None)
        except Exception:
            pass

    # Token holdings and stablecoin balances are independent reads. Execute
    # them concurrently and publish only one completed snapshot to the UI.
    jobs = {'tokens': lambda: d._fetch_wallet_tokens(wallet, onchain_wallet),
            'solana_usdc': lambda: d._get_solana_usdc_balance(onchain_wallet)}
    if evm_address:
        for chain in getattr(d, 'EVM_CHAINS', {}):
            jobs['stable:' + chain] = (lambda ch=chain: d.get_evm_usdc_balance(evm_address, ch))

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
    evm_chains = {chain: round(_num(results.get('stable:' + chain)), 6)
                  for chain in getattr(d, 'EVM_CHAINS', {})}
    stable_total = solana_usdc + sum(evm_chains.values())

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
        'wallets': {'solana': onchain_wallet, 'evm': evm_address},
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
            app.logger.warning('portfolio snapshot failed: %s', type(exc).__name__)
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
