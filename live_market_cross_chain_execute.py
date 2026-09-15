"""Route Live Market trade-engine BUYs through auto-bridge when needed.

The Live Market sheet intentionally shows the wallet-wide stablecoin balance.
The trade-engine execute endpoint, however, still checked only the destination
chain balance. For an EVM destination such as Robinhood this meant a user could
see $5+ available but execution would reserve against the ~$0 already on
Robinhood and fail before the existing auto-bridge machinery ever ran.

This wrapper keeps the trade engine unchanged for same-chain buys. When an
EVM destination cannot cover the stored quote, it starts OrcAgent's existing
auto-bridge-then-buy state machine instead. That helper is already wrapped by
the all-in budget guard and Solana gasless bootstrap, so the user-entered amount
remains the absolute ceiling and OrcAgent never fronts user gas.
"""
from __future__ import annotations

import functools
import sqlite3
from decimal import Decimal

from flask import request


def install(d):
    app = d.app
    if getattr(app, '_orca_cross_chain_execute_installed', False):
        return
    app._orca_cross_chain_execute_installed = True

    endpoint = 'api_trade_execute'
    original = app.view_functions.get(endpoint)
    if not callable(original):
        raise RuntimeError('api_trade_execute endpoint is unavailable')

    @functools.wraps(original)
    def execute_with_auto_bridge(*args, **kwargs):
        # Preserve the original endpoint as the authority for malformed,
        # unauthenticated, non-EVM, same-chain and already-funded requests.
        try:
            wallet = d._authenticated_wallet()
            data = request.get_json(silent=True) or {}
            quote_id = str(data.get('quote_id') or '').strip()
            if not wallet or not quote_id:
                return original(*args, **kwargs)

            conn = sqlite3.connect(d.DB_FILE)
            try:
                quote = d.te_ledger.load_quote(conn, quote_id)
                row = conn.execute(
                    'SELECT id, bsc_wallet_address FROM users WHERE wallet_address=?',
                    (wallet,),
                ).fetchone()
            finally:
                conn.close()

            if not quote or not row:
                return original(*args, **kwargs)
            user_id, evm_address = row
            if int(quote.get('user_id') or -1) != int(user_id):
                return original(*args, **kwargs)
            if str(quote.get('wallet') or '') != str(wallet):
                return original(*args, **kwargs)

            chain = str(quote.get('destination_chain') or '').strip().lower()
            if chain not in getattr(d, 'EVM_CHAINS', {}):
                return original(*args, **kwargs)
            if not evm_address:
                return original(*args, **kwargs)

            required = Decimal(str(quote.get('total_cost_usd') or '0'))
            ceiling = Decimal(str(quote.get('max_spend_usd') or required or '0'))
            if required <= 0 or ceiling <= 0:
                return original(*args, **kwargs)

            try:
                destination_balance = Decimal(str(
                    d.get_evm_usdc_balance(evm_address, chain) or 0
                ))
            except Exception:
                # Let the established endpoint return its normal balance-read
                # error instead of converting an RPC outage into bridge logic.
                return original(*args, **kwargs)

            if destination_balance + Decimal('0.000001') >= required:
                return original(*args, **kwargs)

            token_address = str(quote.get('token_address') or '').strip()
            bridge = d._maybe_start_auto_bridge_for_buy(
                int(user_id), wallet, evm_address, chain, token_address,
                float(ceiling),
            )
            if isinstance(bridge, dict) and bridge.get('started'):
                return d.jsonify({
                    'ok': True,
                    'pending': True,
                    'bridge_id': bridge.get('bridge_id'),
                    'quote_id': quote_id,
                    'chain': chain,
                    'token_address': token_address,
                    'amount_usdc': float(ceiling),
                    'msg': 'Buying...',
                })

            reason = (bridge or {}).get('msg') if isinstance(bridge, dict) else ''
            return d.jsonify({
                'ok': False,
                'msg': reason or 'Could not start automatic cross-chain funding',
            }), 400
        except Exception as exc:
            # A wrapper failure must never make the trading endpoint disappear.
            # Fall through to the original endpoint, which retains its own
            # validation, authorization and error handling.
            try:
                app.logger.warning('cross-chain execute preflight skipped: %s', exc)
            except Exception:
                pass
            return original(*args, **kwargs)

    app.view_functions[endpoint] = execute_with_auto_bridge
