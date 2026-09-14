"""Cross-chain all-in budget guard.

Product invariant: the number a user types is the maximum total amount that
may leave their stablecoin balance for the buy flow.  No bridge buffer may be
added on top and OrcAgent never supplies user gas.

This module deliberately wraps the existing bridge state machines instead of
creating a second implementation.  It fixes two legacy edges:

1. EVM-destination auto-bridge used to ask the source chain for 105% of the
   requested amount (5% bridge buffer).  We reduce the attached buy budget
   before handing it to that legacy helper, so its own 5% buffer can never
   make the source transfer exceed the user's ceiling.
2. EVM -> Solana used to require an already-funded SOL reserve after USDC had
   arrived.  When Jupiter Ultra gasless is configured, destination SOL is not
   a prerequisite; Jupiter recovers network/rent costs inside the swap.
"""
from __future__ import annotations

import inspect
import json
import os
import sqlite3
from decimal import Decimal, ROUND_DOWN


def _d(value) -> Decimal:
    return Decimal(str(value))


def _gasless_solana_enabled() -> bool:
    return bool((os.getenv('JUPITER_API_KEY', '') or '').strip())


def _json_body(response):
    try:
        return response.get_json(silent=True) or {}
    except Exception:
        return {}


def install(d):
    if getattr(d, '_orca_cross_chain_budget_guard_installed', False):
        return
    d._orca_cross_chain_budget_guard_installed = True

    # ── EVM destination: neutralise the legacy +5% bridge buffer ──────────
    original_auto_bridge = getattr(d, '_maybe_start_auto_bridge_for_buy', None)
    if original_auto_bridge is not None:
        def guarded_auto_bridge(user_id, wallet, evm_address, dest_chain,
                                token_address, amount_usdc):
            try:
                ceiling = _d(amount_usdc)
                if ceiling <= 0:
                    return {'started': False, 'msg': 'Trade amount must be greater than zero'}
                legacy_buffer = _d(getattr(d, '_AUTO_BRIDGE_BUFFER_PCT', '0.05'))
                # The legacy helper computes bridge_amount = buy_budget *
                # (1 + buffer).  Solve backwards so bridge_amount <= ceiling.
                buy_budget = (ceiling / (Decimal('1') + legacy_buffer)).quantize(
                    Decimal('0.000001'), rounding=ROUND_DOWN)
                if buy_budget <= 0:
                    return {'started': False, 'msg': 'Trade amount is too small after bridge reserve'}
                result = original_auto_bridge(
                    user_id, wallet, evm_address, dest_chain,
                    token_address, float(buy_budget))
                if isinstance(result, dict) and result.get('started'):
                    result['max_spend_usdc'] = str(ceiling)
                    result['auto_buy_budget_usdc'] = str(buy_budget)
                return result
            except Exception as exc:
                return {'started': False, 'msg': f'Could not price automatic bridge safely: {exc}'}

        d._maybe_start_auto_bridge_for_buy = guarded_auto_bridge

    # ── EVM -> Solana: Jupiter gasless means destination SOL is not needed ─
    try:
        import evm_to_solana_bridge as reverse
    except Exception:
        reverse = None

    if reverse is not None:
        original_sol_budget = getattr(reverse, '_solana_gas_budget_usd', None)
        if original_sol_budget is not None:
            def solana_gas_budget(appmod):
                if _gasless_solana_enabled():
                    return 0.0
                return original_sol_budget(appmod)
            reverse._solana_gas_budget_usd = solana_gas_budget

        original_after_bridge = getattr(reverse, '_solana_auto_buy_after_bridge', None)
        if original_after_bridge is not None:
            def gasless_after_bridge(appmod, bridge_id, user_id, wallet,
                                     token_address, requested_usdc):
                if not _gasless_solana_enabled():
                    return original_after_bridge(
                        appmod, bridge_id, user_id, wallet,
                        token_address, requested_usdc)
                try:
                    trading_wallet = appmod._get_trading_wallet_address(wallet)
                    if not trading_wallet:
                        reverse._mark_auto_buy(appmod, bridge_id, 'failed', {
                            'error': 'Solana trading wallet is not configured',
                            'chain': 'solana'
                        })
                        return

                    # Settlement is the source of truth.  Never spend more
                    # than either what actually landed or the attached budget.
                    solana_usdc = float(appmod._get_solana_usdc_balance(trading_wallet))
                    spend = min(float(requested_usdc or 0), solana_usdc)
                    minimum = float(getattr(appmod, 'SOLANA_MIN_SPEND_USDC', 1.0) or 1.0)
                    if spend + 1e-9 < minimum:
                        reverse._mark_auto_buy(appmod, bridge_id, 'failed', {
                            'error': 'Funds arrived but not enough USDC is available for the Solana buy',
                            'available_usdc': solana_usdc,
                            'chain': 'solana'
                        })
                        return

                    flow = appmod._solana_buy_flow
                    supported = inspect.signature(flow).parameters
                    kwargs = {}
                    if 'requested_usdc' in supported:
                        kwargs['requested_usdc'] = spend
                    if 'log_label' in supported:
                        kwargs['log_label'] = 'AUTO BUY'
                    if 'enforce_position_cap' in supported:
                        kwargs['enforce_position_cap'] = False
                    if 'idle_note' in supported:
                        kwargs['idle_note'] = ''
                    if 'is_copy' in supported:
                        kwargs['is_copy'] = False

                    with appmod.app.app_context():
                        rv = flow(wallet, token_address, **kwargs)
                        response = appmod.app.make_response(rv)
                    body = _json_body(response)
                    ok = response.status_code < 400 and bool(body.get('ok') or body.get('success'))
                    if not ok:
                        reverse._mark_auto_buy(appmod, bridge_id, 'failed', {
                            'error': body.get('msg') or body.get('error') or 'Solana buy did not complete',
                            'available_usdc': solana_usdc,
                            'chain': 'solana'
                        })
                        return

                    reverse._mark_auto_buy(appmod, bridge_id, 'done', {
                        'symbol': body.get('symbol') or token_address[:8],
                        'amount_usdc': body.get('spend', body.get('amount_usdc', spend)),
                        'tx_hash': body.get('tx_hash') or body.get('tx') or body.get('sig')
                                   or body.get('signature') or '',
                        'chain': 'solana',
                        'gasless': True,
                    })
                except Exception as exc:
                    print(f'[cross-chain-budget] Solana post-bridge buy failed for row {bridge_id}: {exc}', flush=True)
                    try:
                        reverse._mark_auto_buy(appmod, bridge_id, 'failed', {
                            'error': str(exc) or 'Solana buy failed after bridge',
                            'chain': 'solana'
                        })
                    except Exception:
                        pass

            reverse._solana_auto_buy_after_bridge = gasless_after_bridge
