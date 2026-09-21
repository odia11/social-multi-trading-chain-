"""Bootstrap Solana origin gas from the user's own USDC for cross-chain BUYs.

When a cross-chain BUY is funded from Solana and the trading wallet has zero
SOL, OrcAgent must not ask the user to top up manually. It may use only the
user's own USDC inside the amount they already approved: obtain a genuinely
gasless Jupiter Ultra USDC -> SOL order, execute just enough for the Solana
origin fee, then retry the existing bridge with the remaining budget.

OrcAgent never subsidises this flow. If Jupiter cannot provide a gasless route,
the exact reason is returned to Live Market instead of hiding it behind the
legacy "deposit SOL first" error.
"""
from __future__ import annotations

import sqlite3
import time
from decimal import Decimal, ROUND_DOWN

import requests
from solders.keypair import Keypair

import solana_gasless_trading as jup

_SOL_MINT = 'So11111111111111111111111111111111111111112'
_MIN_BOOTSTRAP_USDC = Decimal('0.20')
_USDC_STEP = Decimal('0.20')
_LAMPORTS_PER_SOL = Decimal('1000000000')
_Q6 = Decimal('0.000001')


def _q6(value) -> Decimal:
    return Decimal(str(value)).quantize(_Q6, rounding=ROUND_DOWN)


def _gasless_order(private_key: str, amount_usdc: Decimal):
    """Quote a gasless USDC -> SOL order without spending anything yet."""
    amount_usdc = _q6(amount_usdc)
    if amount_usdc <= 0:
        raise RuntimeError('gas bootstrap amount must be positive')

    raw = amount_usdc * Decimal(1_000_000)
    kp = Keypair.from_base58_string(private_key)
    params = {
        'inputMint': jup._USDC,
        'outputMint': _SOL_MINT,
        'amount': str(int(raw)),
        'taker': str(kp.pubkey()),
    }
    r = requests.get(jup._API + '/order', params=params,
                     headers=jup._headers(), timeout=20)
    try:
        order = r.json()
    except Exception:
        raise RuntimeError(
            f'Jupiter gas bootstrap returned HTTP {r.status_code} with non-JSON response')

    if not r.ok:
        reason = order.get('error') or order.get('errorMessage') or order.get('message') or order
        raise RuntimeError(f'Jupiter gas bootstrap failed (HTTP {r.status_code}): {reason}')
    if not order.get('transaction'):
        raise RuntimeError(str(order.get('errorMessage') or order.get('error')
                               or 'Jupiter returned no executable gas-bootstrap transaction')[:300])
    if not bool(order.get('gasless')):
        raise RuntimeError('Jupiter did not provide a gasless USDC -> SOL route')

    try:
        out_raw = int(order.get('outAmount') or 0)
    except Exception:
        out_raw = 0
    if out_raw <= 0:
        raise RuntimeError('Jupiter gasless USDC -> SOL quote returned no SOL output')
    quoted_sol = Decimal(out_raw) / _LAMPORTS_PER_SOL
    return order, quoted_sol


def _pick_gasless_order(private_key: str, max_spend_usdc: Decimal,
                        sol_shortfall: Decimal):
    """Find the smallest gasless order that covers the actual SOL shortfall."""
    max_spend_usdc = _q6(max_spend_usdc)
    if max_spend_usdc < _MIN_BOOTSTRAP_USDC:
        raise RuntimeError('buy budget is too small to fund Solana bridge gas')

    candidate = min(_MIN_BOOTSTRAP_USDC, max_spend_usdc)
    last_error = ''
    while candidate <= max_spend_usdc:
        try:
            order, quoted_sol = _gasless_order(private_key, candidate)
            if quoted_sol >= sol_shortfall:
                return candidate, order, quoted_sol
        except Exception as exc:
            last_error = str(exc)
            low = last_error.lower()
            if ('api_key' in low or 'api key' in low or '401' in low or
                    '403' in low or 'unauthor' in low or 'forbidden' in low):
                raise

        if candidate >= max_spend_usdc:
            break
        nxt = min(max_spend_usdc, max(candidate * 2, candidate + _USDC_STEP))
        nxt = _q6(nxt)
        if nxt <= candidate:
            break
        candidate = nxt

    if last_error:
        raise RuntimeError(last_error)
    raise RuntimeError(
        'No Jupiter gasless USDC -> SOL amount inside this buy budget can fund Solana bridge gas')


def _execute_order(private_key: str, order: dict):
    signed = jup._sign_for_taker(private_key, order['transaction'])
    return jup._execute(order, signed)


def install(d):
    if getattr(d, '_orca_solana_source_bridge_gasless_installed', False):
        return
    d._orca_solana_source_bridge_gasless_installed = True

    original = getattr(d, '_maybe_start_auto_bridge_for_buy', None)
    if not callable(original):
        raise RuntimeError('automatic bridge helper is unavailable')

    def _solana_key_row(wallet: str):
        conn = sqlite3.connect(d.DB_FILE)
        try:
            return conn.execute(
                'SELECT id, encrypted_private_key FROM users WHERE wallet_address=?',
                (wallet,),
            ).fetchone()
        finally:
            conn.close()

    def _failure(wallet: str, reason: str):
        safe = d._redact_keys(str(reason))[:320]
        try:
            d.add_user_log(wallet, '[bridge] Solana gas bootstrap failed: ' + safe)
        except Exception:
            pass
        return {
            'started': False,
            'msg': 'Could not fund Solana bridge gas automatically from your USDC: ' + safe,
        }

    def user_funded_solana_topup(wallet: str, max_spend_usdc,
                                  target_sol=0.0035):
        """Convert this user's own Solana USDC into enough SOL for network use.

        This never touches a sponsor/platform wallet. It is suitable for any
        user-authorised action (tip/send/bridge) that already has USDC but
        lacks native SOL. Returns a small result dict for the caller.
        """
        max_spend = _q6(max_spend_usdc)
        if max_spend < _MIN_BOOTSTRAP_USDC:
            raise RuntimeError(
                f'At least ${float(_MIN_BOOTSTRAP_USDC):.2f} spare USDC is needed '
                'to create Solana network gas automatically')

        row = _solana_key_row(wallet)
        if not row or not row[1]:
            raise RuntimeError('Solana trading key is not configured')
        enc_blob = row[1]
        trading_address = d._get_trading_wallet_address(wallet)
        if not trading_address:
            raise RuntimeError('Solana trading wallet is not configured')

        current_sol = Decimal(str(d._get_user_sol(trading_address) or 0))
        target = Decimal(str(target_sol or 0.0035))
        if target <= 0:
            target = Decimal('0.0035')
        if current_sol >= target:
            return {
                'ok': True, 'spent_usdc': Decimal('0'),
                'before_sol': current_sol, 'after_sol': current_sol,
            }

        shortfall = target - current_sol
        try:
            sol_usdc = _q6(d._get_solana_usdc_balance(trading_address) or 0)
        except Exception:
            # Caller already capped max_spend to spare on-chain USDC. If the
            # mint-only RPC is temporarily unavailable, do not repeat the same
            # failing balance read and block an otherwise valid gasless order.
            sol_usdc = max_spend
        budget = min(max_spend, sol_usdc)
        if budget < _MIN_BOOTSTRAP_USDC:
            raise RuntimeError('Not enough spare USDC is available to create Solana network gas')

        with d._use_key(enc_blob, wallet) as private_key:
            used_usdc, order, quoted_sol = _pick_gasless_order(
                private_key, budget, shortfall)
            _execute_order(private_key, order)

        actual_sol = current_sol
        for _ in range(10):
            try:
                actual_sol = Decimal(str(d._get_user_sol(trading_address) or 0))
            except Exception:
                actual_sol = current_sol
            if actual_sol > current_sol:
                break
            time.sleep(0.5)
        if actual_sol <= current_sol:
            raise RuntimeError(
                'Gasless SOL top-up confirmed but the SOL balance has not updated yet')

        try:
            d.add_user_log(
                wallet,
                f'[gas] Converted ${float(used_usdc):.2f} USDC to '
                f'{float(quoted_sol):.6f} SOL from the user wallet')
        except Exception:
            pass
        return {
            'ok': True, 'spent_usdc': used_usdc,
            'before_sol': current_sol, 'after_sol': actual_sol,
            'quoted_sol': quoted_sol,
        }

    d._gasless_solana_native_topup = user_funded_solana_topup

    def auto_bridge(user_id, wallet, evm_address, dest_chain,
                    token_address, amount_usdc):
        first = original(user_id, wallet, evm_address, dest_chain,
                         token_address, amount_usdc)
        if not isinstance(first, dict) or first.get('started'):
            return first
        msg = str(first.get('msg') or '')
        if 'insufficient sol' not in msg.lower() or 'solana' not in msg.lower():
            return first

        try:
            ceiling = _q6(amount_usdc)
            minimum_buy = _q6(getattr(d, 'SOLANA_MIN_SPEND_USDC', 1.0) or 1.0)
            max_bootstrap = _q6(ceiling - minimum_buy)
            if max_bootstrap < _MIN_BOOTSTRAP_USDC:
                return _failure(wallet, 'buy amount is too small after reserving the final token purchase')

            row = _solana_key_row(wallet)
            if not row or not row[1]:
                return _failure(wallet, 'Solana trading key is not configured')
            enc_blob = row[1]
            trading_address = d._get_trading_wallet_address(wallet)
            if not trading_address:
                return _failure(wallet, 'Solana trading wallet is not configured')

            current_sol = Decimal(str(d._get_user_sol(trading_address) or 0))
            # A cross-chain origin transaction does NOT need OrcAgent's full
            # 0.005 SOL trading reserve. That reserve is for keeping enough SOL
            # around for later Solana buys/sells too. Here we only bootstrap the
            # source bridge transaction. Keeping the two values coupled made a
            # $1.30 Robinhood buy reserve ~$1+ of SOL before the bridge and fail
            # even though the bridge itself needs only a fraction of that.
            # The bridge-specific reserve is configurable; 0.001 SOL is the
            # conservative default and still remains fully user-funded.
            bridge_reserve = getattr(d, 'SOL_BRIDGE_GAS_RESERVE', 0.001)
            target_sol = Decimal(str(bridge_reserve or 0.001))
            if target_sol <= 0:
                target_sol = Decimal('0.001')
            if current_sol >= target_sol:
                return original(user_id, wallet, evm_address, dest_chain,
                                token_address, float(ceiling))
            shortfall = target_sol - current_sol

            sol_usdc = _q6(d._get_solana_usdc_balance(trading_address) or 0)
            max_bootstrap = min(max_bootstrap, sol_usdc)
            if max_bootstrap < _MIN_BOOTSTRAP_USDC:
                return _failure(wallet, 'not enough Solana USDC is available to create origin network gas')

            with d._use_key(enc_blob, wallet) as private_key:
                used_usdc, order, quoted_sol = _pick_gasless_order(
                    private_key, max_bootstrap, shortfall)
                _execute_order(private_key, order)

            actual_sol = current_sol
            for _ in range(8):
                try:
                    actual_sol = Decimal(str(d._get_user_sol(trading_address) or 0))
                except Exception:
                    actual_sol = current_sol
                if actual_sol > current_sol:
                    break
                time.sleep(0.5)
            if actual_sol <= current_sol:
                return _failure(wallet,
                                'Jupiter confirmed the gasless swap but the SOL balance did not increase yet')

            remaining = _q6(ceiling - used_usdc)
            if remaining < minimum_buy:
                return _failure(wallet, 'gas bootstrap would leave less than the minimum token buy')

            d.add_user_log(
                wallet,
                f'[bridge] Converted ${float(used_usdc):.2f} USDC to SOL gas '
                f'({float(quoted_sol):.6f} SOL quoted); continuing {dest_chain} buy.'
            )
            retried = original(user_id, wallet, evm_address, dest_chain,
                               token_address, float(remaining))
            if isinstance(retried, dict) and not retried.get('started'):
                retry_msg = str(retried.get('msg') or '')
                if 'insufficient sol' in retry_msg.lower():
                    retried = dict(retried)
                    retried['msg'] = (
                        'Gasless SOL bootstrap completed, but the bridge still requires more SOL. '
                        f'Current balance: {float(actual_sol):.6f} SOL. ' + retry_msg)
            return retried
        except Exception as exc:
            return _failure(wallet, exc)

    d._maybe_start_auto_bridge_for_buy = auto_bridge
