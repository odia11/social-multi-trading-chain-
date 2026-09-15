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


def _num(v, default=0.0):
    try:
        return float(v if v is not None else default)
    except Exception:
        return float(default)


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

            state = d.get_user_state(wallet) or {}
            positions = state.get('positions') or {}

            seen = set()
            for t in tokens:
                addr = str(t.get('mint') or t.get('address') or t.get('token_address') or '').lower()
                chain = str(t.get('chain') or 'solana').lower()
                if addr:
                    seen.add((chain, addr))

            supported = {'bsc', 'base', 'arbitrum', 'polygon', 'robinhood'}
            for address, pos in positions.items():
                if not isinstance(pos, dict):
                    continue
                chain = str(pos.get('chain') or pos.get('network') or '').lower()
                if chain not in supported:
                    continue
                token_address = str(pos.get('token_address') or pos.get('mint') or address or '').strip()
                if not token_address or (chain, token_address.lower()) in seen:
                    continue
                amount = _num(pos.get('amount', pos.get('token_amount', 0)))
                if amount <= 0:
                    continue

                symbol = str(pos.get('symbol') or pos.get('token') or token_address[:8]).replace('$', '')
                name = str(pos.get('name') or symbol)
                buy_price = _num(pos.get('buy_price', pos.get('entry_price', 0)))
                price = _num(pos.get('price_usd', pos.get('current_price', 0)))
                try:
                    td = d.get_token_data(token_address)
                    if td:
                        symbol = str(td.get('symbol') or symbol).replace('$', '')
                        name = str(td.get('name') or name)
                        price = _num(td.get('price', td.get('price_usd', price)), price)
                except Exception:
                    pass

                usd_value = amount * price if price > 0 else _num(pos.get('spend', pos.get('cost_basis', 0)))
                tokens.append({
                    'mint': token_address,
                    'address': token_address,
                    'token_address': token_address,
                    'symbol': symbol,
                    'name': name,
                    'amount': amount,
                    'price_usd': price,
                    'usd_value': usd_value,
                    'value_usd': usd_value,
                    'avg_price': buy_price,
                    'chain': chain,
                    'is_evm': True,
                })
                seen.add((chain, token_address.lower()))

            body['tokens'] = tokens
            body['ok'] = body.get('ok', True)
            body['multichain'] = True
            response = d.jsonify(body)
        except Exception as exc:
            app.logger.warning('multichain portfolio merge failed: %s', exc)
        return response

    app.view_functions[endpoint] = multichain_wallet_tokens

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
