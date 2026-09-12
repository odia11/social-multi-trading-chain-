"""Automatic EVM -> Solana USDC bridge for Solana buys.

The application already has the hard parts:
- _execute_cross_chain_bridge() signs and submits the existing 0x cross-chain
  route and records it in bridge_transactions;
- _bridge_status_loop() atomically claims an attached buy with
  pending -> processing before calling _execute_auto_buy_after_bridge();
- Live Market already understands {ok:true,pending:true,bridge_id:...} and
  silently polls /api/bridge/status/<id> until the attached buy finishes.

What was missing was only the reverse direction. The old automatic helper
assumes EVM_CHAINS[dest_chain], so dest_chain='solana' cannot use it, and the
post-bridge continuation only knew how to execute an EVM swap.

This module installs two narrow adapters after dashboard has fully imported:
1. /api/instant-trade is allowed to behave exactly as before. ONLY when a
   valid Solana buy is refused specifically for insufficient Solana USDC do
   we look for an EVM chain with enough user-owned USDC and user-paid native
   gas, then start the existing bridge with that buy attached.
2. The existing bridge continuation delegates every EVM destination to the
   original implementation. For dest_chain='solana' it re-reads the REAL
   Solana USDC balance after settlement and invokes the shared Solana/Jupiter
   buy flow with at most the originally requested amount.

No platform prefunding is introduced here. An EVM source that needs sponsored
native gas is skipped, and the existing bridge executor has its own EVM gas
pre-check as a second line of defence. The Solana continuation also requires
its own network-fee reserve before calling the shared buy flow, so this
extension itself never triggers a sponsor grant. If either side cannot pay
its own network fee, the bridged USDC stays safely in the user's wallet and
the attached buy is marked failed instead of spending platform funds.
"""
from __future__ import annotations

import inspect
import json
import sqlite3
from typing import Any, Dict, Optional, Tuple


def _json_body(response) -> Dict[str, Any]:
    try:
        return response.get_json(silent=True) or {}
    except Exception:
        return {}


def _user_row(appmod, wallet: str):
    """Return (user_id, shared_evm_address) for the authenticated wallet."""
    conn = sqlite3.connect(appmod.DB_FILE)
    try:
        return conn.execute(
            "SELECT id, bsc_wallet_address FROM users WHERE wallet_address=?",
            (wallet,),
        ).fetchone()
    finally:
        conn.close()


def _existing_pending_bridge(appmod, user_id: int, token_address: str) -> Optional[int]:
    """A repeated Buy press must attach to, never duplicate, an in-flight move."""
    conn = sqlite3.connect(appmod.DB_FILE)
    try:
        row = conn.execute(
            """SELECT id FROM bridge_transactions
               WHERE user_id=? AND dest_chain='solana'
                 AND auto_buy_token_address=?
                 AND auto_buy_status IN ('pending','processing')
                 AND status NOT IN ('bridge_failed','origin_tx_reverted','timed_out')
               ORDER BY id DESC LIMIT 1""",
            (user_id, token_address),
        ).fetchone()
        return int(row[0]) if row else None
    finally:
        conn.close()


def _source_needs_sponsored_gas(appmod, chain: str, evm_address: str) -> bool:
    """Read-only test. Never tops gas up and never spends platform funds."""
    checker = getattr(appmod, '_te_needs_sponsored_gas', None)
    if checker is not None:
        try:
            return bool(checker(chain, evm_address))
        except Exception:
            # Do not guess that a wallet can pay gas when the check itself is
            # unavailable. The bridge executor would refuse too, but skipping
            # here avoids selecting a source we cannot prove usable.
            return True

    # Older deployments may not expose the trade-engine helper. Use the same
    # read-only native-balance threshold as the gas manager if possible.
    try:
        w3 = appmod._get_web3(chain)
        address = w3.to_checksum_address(evm_address)
        balance = int(w3.eth.get_balance(address))
        needed = int(w3.eth.gas_price) * int(appmod.GAS_TOPUP_TX_GAS_UNITS)
        return balance < needed
    except Exception:
        return True


def _pick_evm_source(appmod, evm_address: str, needed_usdc: float) -> Optional[Tuple[str, str, float]]:
    """Pick the richest EVM source that can pay BOTH the funds and its own gas.

    Solana is deliberately not a candidate: this module exists only for the
    reverse direction EVM -> Solana. EVM_CHAINS holds the on-chain stablecoin
    address for every supported EVM network (USDG on Robinhood underneath,
    while the user-facing amount remains USDC).
    """
    if not evm_address:
        return None
    buffer_pct = float(getattr(appmod, '_AUTO_BRIDGE_BUFFER_PCT', 0.05) or 0.05)
    needed_with_buffer = float(needed_usdc) * (1.0 + buffer_pct)
    candidates = []
    for chain, cfg in getattr(appmod, 'EVM_CHAINS', {}).items():
        try:
            balance = float(appmod.get_evm_usdc_balance(evm_address, chain))
        except Exception as exc:
            print(f'[evm->solana] {chain} balance check failed: {exc}', flush=True)
            continue
        if balance + 1e-9 < needed_with_buffer:
            continue
        if _source_needs_sponsored_gas(appmod, chain, evm_address):
            print(f'[evm->solana] skipping {chain}: source wallet cannot pay its own bridge gas', flush=True)
            continue
        token = (cfg or {}).get('usdc')
        if token:
            candidates.append((chain, token, balance))
    return max(candidates, key=lambda item: item[2]) if candidates else None


def _mark_auto_buy(appmod, bridge_id: int, status: str, result: Dict[str, Any]) -> None:
    """Only the status-loop-claimed ('processing') continuation may finish it."""
    conn = sqlite3.connect(appmod.DB_FILE)
    try:
        conn.execute(
            """UPDATE bridge_transactions
               SET auto_buy_status=?, auto_buy_result=?
               WHERE id=? AND auto_buy_status='processing'""",
            (status, json.dumps(result, separators=(',', ':'), default=str), bridge_id),
        )
        conn.commit()
    finally:
        conn.close()


def _solana_auto_buy_after_bridge(appmod, bridge_id: int, user_id: int, wallet: str,
                                   token_address: str, requested_usdc: float) -> None:
    """Execute the existing USDC-funded Jupiter buy after bridge settlement."""
    try:
        trading_wallet = appmod._get_trading_wallet_address(wallet)
        if not trading_wallet:
            _mark_auto_buy(appmod, bridge_id, 'failed', {
                'error': 'Solana trading wallet is not configured', 'chain': 'solana'
            })
            return

        # Never trust the bridge quote/output as spendable funds. The same
        # rule as the existing EVM continuation: re-read what actually landed.
        solana_usdc = float(appmod._get_solana_usdc_balance(trading_wallet))
        spend = min(float(requested_usdc or 0), solana_usdc)
        min_spend = float(getattr(appmod, 'SOLANA_MIN_SPEND_USDC', 1.0) or 1.0)
        if spend + 1e-9 < min_spend:
            _mark_auto_buy(appmod, bridge_id, 'failed', {
                'error': 'Funds arrived but not enough USDC is available for the requested Solana buy',
                'available_usdc': solana_usdc, 'chain': 'solana'
            })
            return

        # This extension must not cause a platform-sponsored gas grant. If the
        # destination cannot pay its own network fee, leave the USDC untouched.
        reserve = float(getattr(appmod, 'SOL_NETWORK_RESERVE', 0.005) or 0.005)
        try:
            sol_balance = float(appmod._get_user_sol(trading_wallet))
        except Exception:
            sol_balance = 0.0
        if sol_balance + 1e-12 < reserve:
            _mark_auto_buy(appmod, bridge_id, 'failed', {
                'error': 'USDC arrived on Solana, but the trading wallet needs SOL for its own network fee',
                'available_usdc': solana_usdc, 'chain': 'solana'
            })
            return

        flow = appmod._solana_buy_flow
        sig = inspect.signature(flow)
        kwargs: Dict[str, Any] = {}
        supported = sig.parameters
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

        # _solana_buy_flow is an internal flow, not an HTTP endpoint, and can
        # return either a Flask response or (response,status). make_response
        # normalises both without inventing a second Jupiter implementation.
        with appmod.app.app_context():
            rv = flow(wallet, token_address, **kwargs)
            response = appmod.app.make_response(rv)
        body = _json_body(response)
        ok = response.status_code < 400 and bool(body.get('ok') or body.get('success'))
        if not ok:
            _mark_auto_buy(appmod, bridge_id, 'failed', {
                'error': body.get('msg') or body.get('error') or 'Solana buy did not complete',
                'available_usdc': solana_usdc, 'chain': 'solana'
            })
            return

        result = {
            'symbol': body.get('symbol') or token_address[:8],
            'amount_usdc': body.get('spend', body.get('amount_usdc', spend)),
            'tx_hash': body.get('tx_hash') or body.get('tx') or body.get('sig') or body.get('signature') or '',
            'chain': 'solana',
        }
        _mark_auto_buy(appmod, bridge_id, 'done', result)
    except Exception as exc:
        print(f'[evm->solana] post-bridge buy failed for row {bridge_id}: {exc}', flush=True)
        try:
            _mark_auto_buy(appmod, bridge_id, 'failed', {
                'error': str(exc) or 'Solana buy failed after bridge', 'chain': 'solana'
            })
        except Exception:
            pass


def install(appmod) -> None:
    """Install the reverse auto-bridge once, after dashboard has imported."""
    if getattr(appmod, '_evm_to_solana_bridge_installed', False):
        return

    required = (
        '_execute_cross_chain_bridge', '_execute_auto_buy_after_bridge',
        '_get_solana_usdc_balance', '_solana_buy_flow', 'USDC_MINT', 'EVM_CHAINS'
    )
    missing = [name for name in required if not hasattr(appmod, name)]
    if missing:
        raise RuntimeError('EVM->Solana bridge extension missing dashboard hooks: ' + ', '.join(missing))

    original_continuation = appmod._execute_auto_buy_after_bridge
    original_instant = appmod.app.view_functions.get('api_instant_trade')
    if original_instant is None:
        raise RuntimeError('EVM->Solana bridge extension could not find api_instant_trade')

    def continuation(bridge_id: int, user_id: int, wallet: str, dest_chain: str,
                     token_address: str, requested_usdc: float):
        if str(dest_chain).lower() != 'solana':
            return original_continuation(
                bridge_id, user_id, wallet, dest_chain, token_address, requested_usdc
            )
        return _solana_auto_buy_after_bridge(
            appmod, bridge_id, user_id, wallet, token_address, requested_usdc
        )

    def instant_trade_with_reverse_bridge(*args, **kwargs):
        # First run the real route. Every existing validation/guard therefore
        # stays authoritative. We only replace one very specific refusal.
        rv = original_instant(*args, **kwargs)
        response = appmod.app.make_response(rv)
        body = _json_body(response)
        req = appmod.request.get_json(silent=True) or {}
        side = str(req.get('side') or '').lower()
        reason = str(body.get('error') or body.get('msg') or '')
        if not (side == 'buy' and response.status_code == 400 and 'Not enough USDC' in reason):
            return response

        wallet = appmod._authenticated_wallet()
        token_address = str(req.get('token_address') or '').strip()
        raw_amount = req.get('amount_usdc', req.get('amount_sol'))
        try:
            requested = float(raw_amount)
        except (TypeError, ValueError):
            return response
        if not wallet or not token_address or not (requested > 0):
            return response

        row = _user_row(appmod, wallet)
        if not row or not row[0] or not row[1]:
            return response
        user_id, evm_address = int(row[0]), str(row[1])

        existing = _existing_pending_bridge(appmod, user_id, token_address)
        if existing:
            return appmod.jsonify({
                'ok': True, 'pending': True, 'bridge_id': existing,
                'dest_chain': 'solana'
            })

        source = _pick_evm_source(appmod, evm_address, requested)
        if not source:
            # Keep the original, accurate Solana shortfall response. Either no
            # EVM chain has enough or every funded one lacks its own bridge gas.
            return response

        source_chain, source_token, _balance = source
        buffer_pct = float(getattr(appmod, '_AUTO_BRIDGE_BUFFER_PCT', 0.05) or 0.05)
        bridge_amount = requested * (1.0 + buffer_pct)
        ok, msg_or_tx, bridge_id = appmod._execute_cross_chain_bridge(
            user_id, wallet,
            source_chain, 'solana', source_token, appmod.USDC_MINT,
            bridge_amount,
            initiated_by='auto_buy',
            auto_buy_token_address=token_address,
            auto_buy_requested_usdc=requested,
        )
        if not ok or not bridge_id:
            print(f'[evm->solana] automatic bridge from {source_chain} could not start: {msg_or_tx}', flush=True)
            return appmod.jsonify({
                'ok': False,
                'error': 'Not enough USDC on Solana, and the automatic transfer could not start. '
                         + str(msg_or_tx or '')
            }), 400

        print(
            f'[evm->solana] auto-buy bridge row {bridge_id}: {source_chain} -> solana '
            f'for requested ${requested:.2f}', flush=True
        )
        return appmod.jsonify({
            'ok': True, 'pending': True, 'bridge_id': int(bridge_id),
            'source_chain': source_chain, 'dest_chain': 'solana'
        })

    appmod._execute_auto_buy_after_bridge = continuation
    appmod.app.view_functions['api_instant_trade'] = instant_trade_with_reverse_bridge
    appmod._evm_to_solana_bridge_installed = True
    print('[startup] automatic EVM -> Solana bridge-then-buy enabled', flush=True)
