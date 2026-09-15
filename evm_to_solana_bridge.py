"""Automatic EVM -> Solana USDC bridge for Solana buys.

This is deliberately an adapter around OrcAgent's existing bridge and trade
state machines, not another bridge implementation.

Existing guarantees reused here:
- _execute_cross_chain_bridge() gets the live 0x cross-chain route, signs the
  user's origin transaction and records bridge_transactions;
- _bridge_status_loop() atomically claims an attached buy with
  pending -> processing before calling _execute_auto_buy_after_bridge();
- Live Market already understands {ok:true,pending:true,bridge_id:...} and
  polls /api/bridge/status/<id> until the attached buy finishes.

What this adds:
- a valid Solana buy that is short of Solana USDC may source the money from a
  funded EVM chain;
- once that bridge settles, the normal shared Solana/Jupiter buy flow runs;
- every existing EVM destination still uses the original continuation.

The amount the user types is an ALL-IN ceiling. Before moving USDC we reserve
both the EVM origin gas estimate and a conservative Solana network-fee budget
inside that same amount. 0x bridge fees/slippage come out of the bridge amount
and the Solana platform/Jupiter costs already come out of the amount the
shared buy flow receives. Nothing in this reverse route deliberately spends
`amount + fees`.

No platform prefunding is introduced. An EVM source that needs sponsored gas
is skipped. The destination must already have the user's own Solana gas
reserve as well; otherwise the bridged USDC is left untouched and the attached
buy is marked failed. Existing global sponsor features are not called by this
extension.
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
    conn = sqlite3.connect(appmod.DB_FILE)
    try:
        return conn.execute(
            "SELECT id, bsc_wallet_address FROM users WHERE wallet_address=?",
            (wallet,),
        ).fetchone()
    finally:
        conn.close()


def _existing_pending_bridge(appmod, user_id: int, token_address: str) -> Optional[int]:
    """A retry attaches to an existing move instead of spending twice."""
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
    """Read only. This function NEVER tops gas up."""
    checker = getattr(appmod, '_te_needs_sponsored_gas', None)
    if checker is not None:
        try:
            return bool(checker(chain, evm_address))
        except Exception:
            return True
    try:
        w3 = appmod._get_web3(chain)
        address = w3.to_checksum_address(evm_address)
        balance = int(w3.eth.get_balance(address))
        needed = int(w3.eth.gas_price) * int(appmod.GAS_TOPUP_TX_GAS_UNITS)
        return balance < needed
    except Exception:
        return True


def _source_gas_budget_usd(appmod, chain: str) -> Optional[float]:
    """Reserve origin gas inside the user's dollar ceiling.

    The same live estimator used by OrcAgent's trade-cost engine supplies the
    USD value. A 25% margin makes this conservative for a cross-chain origin
    transaction. If it cannot be priced, auto-bridge is refused rather than
    pretending an unknown cost is zero.
    """
    estimator = getattr(appmod, '_te_gas_usd', None)
    if estimator is None:
        return None
    try:
        estimate = float(estimator(chain))
    except Exception as exc:
        print(f'[evm->solana] {chain} gas price could not be estimated: {exc}', flush=True)
        return None
    if not (estimate >= 0):
        return None
    return estimate * 1.25


def _solana_gas_budget_usd(appmod) -> Optional[float]:
    """Reserve destination network cost inside the same dollar ceiling.

    SOL_NETWORK_RESERVE is intentionally conservative: it is what the existing
    buy flow requires to keep the wallet able to create/send the trade and
    later close it. Multiplying it by the already-live SOL/USD price therefore
    reserves at least the buy-side network cost instead of adding Solana gas on
    top of the number the user typed.
    """
    try:
        reserve_sol = float(getattr(appmod, 'SOL_NETWORK_RESERVE'))
        sol_usd = float(getattr(appmod, '_sol_price_usd'))
    except (TypeError, ValueError, AttributeError):
        return None
    if reserve_sol < 0 or not (sol_usd > 0):
        return None
    return reserve_sol * sol_usd


def _pick_evm_source(appmod, evm_address: str, max_spend_usd: float) \
        -> Optional[Tuple[str, str, float, float, float, float]]:
    """Pick an EVM source while keeping ALL planned costs below the ceiling.

    Returns:
      (chain, stablecoin_address, balance, bridge_amount,
       source_gas_budget_usd, solana_gas_budget_usd)

    `bridge_amount = ceiling - origin gas budget - Solana gas budget`.
    0x's bridge fee/slippage is then deducted from that bridge amount rather
    than charged on top. Solana is never a source candidate here; this module
    owns only the missing EVM -> Solana direction.
    """
    if not evm_address or not (float(max_spend_usd) > 0):
        return None
    dest_gas_budget = _solana_gas_budget_usd(appmod)
    if dest_gas_budget is None:
        print('[evm->solana] cannot price Solana network reserve; reverse auto-bridge skipped', flush=True)
        return None
    min_bridge = float(getattr(appmod, 'SOLANA_MIN_SPEND_USDC', 1.0) or 1.0)
    candidates = []
    for chain, cfg in getattr(appmod, 'EVM_CHAINS', {}).items():
        if _source_needs_sponsored_gas(appmod, chain, evm_address):
            print(f'[evm->solana] skipping {chain}: source wallet cannot pay its own bridge gas', flush=True)
            continue
        source_gas_budget = _source_gas_budget_usd(appmod, chain)
        if source_gas_budget is None:
            continue
        bridge_amount = float(max_spend_usd) - source_gas_budget - dest_gas_budget
        if bridge_amount + 1e-9 < min_bridge:
            continue
        try:
            balance = float(appmod.get_evm_usdc_balance(evm_address, chain))
        except Exception as exc:
            print(f'[evm->solana] {chain} balance check failed: {exc}', flush=True)
            continue
        if balance + 1e-9 < bridge_amount:
            continue
        token = (cfg or {}).get('usdc')
        if token:
            candidates.append(
                (chain, token, balance, bridge_amount, source_gas_budget, dest_gas_budget)
            )
    if not candidates:
        return None
    # Pick the route leaving the largest amount for the actual token buy.
    return max(candidates, key=lambda item: (item[3], item[2]))


def _mark_auto_buy(appmod, bridge_id: int, status: str, result: Dict[str, Any]) -> None:
    """Only the status-loop-claimed processing row may finish an attached buy."""
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
    """After 0x settlement, buy through OrcAgent's existing Jupiter flow."""
    try:
        trading_wallet = appmod._get_trading_wallet_address(wallet)
        if not trading_wallet:
            _mark_auto_buy(appmod, bridge_id, 'failed', {
                'error': 'Solana trading wallet is not configured', 'chain': 'solana'
            })
            return

        # Never trust a quote as money. Re-read the amount that really landed.
        solana_usdc = float(appmod._get_solana_usdc_balance(trading_wallet))
        spend = min(float(requested_usdc or 0), solana_usdc)
        min_spend = float(getattr(appmod, 'SOLANA_MIN_SPEND_USDC', 1.0) or 1.0)
        if spend + 1e-9 < min_spend:
            _mark_auto_buy(appmod, bridge_id, 'failed', {
                'error': 'Funds arrived but not enough USDC is available for the Solana buy',
                'available_usdc': solana_usdc, 'chain': 'solana'
            })
            return

        # Do not call the platform sponsor from this extension. The user must
        # already own the Solana fee reserve that was budgeted above.
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
        supported = inspect.signature(flow).parameters
        kwargs: Dict[str, Any] = {}
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

        # Reuse the tested Jupiter path so fee bundling, position recording,
        # copy triggers and risk state cannot drift into a second implementation.
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

        _mark_auto_buy(appmod, bridge_id, 'done', {
            'symbol': body.get('symbol') or token_address[:8],
            'amount_usdc': body.get('spend', body.get('amount_usdc', spend)),
            'tx_hash': body.get('tx_hash') or body.get('tx') or body.get('sig')
                       or body.get('signature') or '',
            'chain': 'solana',
        })
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
        # Let the real route remain authoritative for auth, limits, mint
        # validation, double-click protection and the already-funded happy path.
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
            max_spend = float(raw_amount)
        except (TypeError, ValueError):
            return response
        if not wallet or not token_address or not (max_spend > 0):
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

        source = _pick_evm_source(appmod, evm_address, max_spend)
        if not source:
            return response

        (source_chain, source_token, _balance, bridge_amount,
         source_gas_budget, solana_gas_budget) = source
        ok, msg_or_tx, bridge_id = appmod._execute_cross_chain_bridge(
            user_id, wallet,
            source_chain, 'solana', source_token, appmod.USDC_MINT,
            bridge_amount,
            initiated_by='auto_buy',
            auto_buy_token_address=token_address,
            # This is what Jupiter may spend after settlement. It is already
            # below the user's original ceiling because both network budgets
            # have been reserved before the bridge begins.
            auto_buy_requested_usdc=bridge_amount,
        )
        if not ok or not bridge_id:
            print(f'[evm->solana] automatic bridge from {source_chain} could not start: {msg_or_tx}', flush=True)
            return appmod.jsonify({
                'ok': False,
                'error': 'Not enough USDC on Solana, and the automatic transfer could not start. '
                         + str(msg_or_tx or '')
            }), 400

        print(
            f'[evm->solana] auto-buy bridge row {bridge_id}: {source_chain} -> solana; '
            f'ceiling=${max_spend:.2f}, source-gas=${source_gas_budget:.2f}, '
            f'solana-gas=${solana_gas_budget:.2f}, bridge=${bridge_amount:.2f}',
            flush=True,
        )
        return appmod.jsonify({
            'ok': True, 'pending': True, 'bridge_id': int(bridge_id),
            'source_chain': source_chain, 'dest_chain': 'solana'
        })

    appmod._execute_auto_buy_after_bridge = continuation
    appmod.app.view_functions['api_instant_trade'] = instant_trade_with_reverse_bridge
    appmod._evm_to_solana_bridge_installed = True
    print('[startup] automatic EVM -> Solana bridge-then-buy enabled', flush=True)
