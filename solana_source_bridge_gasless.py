"""Bootstrap Solana origin gas from the user's own USDC for cross-chain BUYs.

A Live Market BUY can spend wallet-wide USDC.  When that money happens to sit
on Solana and the destination is an EVM chain (notably Robinhood Chain), the
legacy auto-bridge correctly selects Solana as the funding source but then
refuses to broadcast with a zero-SOL trading wallet.

Product invariant: OrcAgent never fronts user gas.  If Jupiter Ultra can make a
gasless USDC -> SOL swap, reserve a small part of the user's *same buy ceiling*
for that bootstrap, then retry the existing auto-bridge with the remainder.
Thus: USDC pays for its own origin gas, bridge costs and final BUY; no platform
wallet subsidises anything and the amount the user entered remains an absolute
maximum.
"""
from __future__ import annotations

import sqlite3
from decimal import Decimal, ROUND_DOWN

import requests
from solders.keypair import Keypair

import solana_gasless_trading as jup

_SOL_MINT = 'So11111111111111111111111111111111111111112'
_MIN_BOOTSTRAP_USDC = Decimal('0.20')
_MARGIN = Decimal('1.20')


def _gasless_usdc_to_sol(d, private_key: str, amount_usdc: Decimal):
    """Swap only the user's USDC into SOL through Jupiter Ultra gasless.

    This deliberately does not attach OrcAgent's trading referral fee: this is
    network plumbing, not a token purchase.  Jupiter's own gasless economics
    remain inside the exact USDC input amount.
    """
    amount_usdc = Decimal(str(amount_usdc)).quantize(Decimal('0.000001'), rounding=ROUND_DOWN)
    if amount_usdc <= 0:
        raise RuntimeError('gas bootstrap amount must be positive')
    raw = amount_usdc * Decimal(1_000_000)
    if raw != raw.to_integral_value():
        raise RuntimeError('gas bootstrap amount has more than 6 decimals')

    kp = Keypair.from_base58_string(private_key)
    taker = str(kp.pubkey())
    params = {
        'inputMint': jup._USDC,
        'outputMint': _SOL_MINT,
        'amount': str(int(raw)),
        'taker': taker,
    }
    r = requests.get(jup._API + '/order', params=params,
                     headers=jup._headers(), timeout=20)
    try:
        order = r.json()
    except Exception:
        raise RuntimeError(f'Jupiter gas bootstrap returned HTTP {r.status_code} with non-JSON response')
    if not r.ok:
        raise RuntimeError(str(order.get('error') or order.get('message') or order)[:300])
    if not order.get('transaction'):
        raise RuntimeError(str(order.get('errorMessage') or order.get('error')
                               or 'Jupiter returned no executable gas-bootstrap transaction')[:300])
    if not bool(order.get('gasless')):
        raise RuntimeError('Jupiter did not provide a gasless USDC -> SOL route')

    signed = jup._sign_for_taker(private_key, order['transaction'])
    signature, result = jup._execute(order, signed)
    return signature, result


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

    def auto_bridge(user_id, wallet, evm_address, dest_chain,
                    token_address, amount_usdc):
        # First use the existing path unchanged.  We intervene only in the one
        # dead-end proven by the returned error: Solana was selected as source
        # but that source has no SOL to broadcast its bridge transaction.
        first = original(user_id, wallet, evm_address, dest_chain,
                         token_address, amount_usdc)
        if not isinstance(first, dict) or first.get('started'):
            return first
        msg = str(first.get('msg') or '')
        if 'insufficient sol' not in msg.lower() or 'solana' not in msg.lower():
            return first

        try:
            ceiling = Decimal(str(amount_usdc))
            minimum_buy = Decimal(str(getattr(d, 'SOLANA_MIN_SPEND_USDC', 1.0) or 1.0))
            if ceiling <= minimum_buy + _MIN_BOOTSTRAP_USDC:
                return first

            row = _solana_key_row(wallet)
            if not row or not row[1]:
                return first
            enc_blob = row[1]
            trading_address = d._get_trading_wallet_address(wallet)
            if not trading_address:
                return first

            current_sol = Decimal(str(d._get_user_sol(trading_address) or 0))
            target_sol = Decimal(str(getattr(d, 'SOL_NETWORK_RESERVE', 0.005) or 0.005))
            if current_sol >= target_sol:
                # Balance may have changed between the failed attempt and here.
                return original(user_id, wallet, evm_address, dest_chain,
                                token_address, float(ceiling))

            sol_price = Decimal(str(getattr(d, '_sol_price_usd', 0) or 0))
            if sol_price <= 0:
                return first

            needed_usdc = ((target_sol - current_sol) * sol_price * _MARGIN)
            needed_usdc = max(needed_usdc, _MIN_BOOTSTRAP_USDC)
            needed_usdc = needed_usdc.quantize(Decimal('0.000001'), rounding=ROUND_DOWN)

            # The gas swap plus everything the retried bridge can spend must
            # stay inside exactly what the user entered.
            max_bootstrap = ceiling - minimum_buy
            if needed_usdc <= 0 or needed_usdc > max_bootstrap:
                return first

            sol_usdc = Decimal(str(d._get_solana_usdc_balance(trading_address) or 0))
            if sol_usdc + Decimal('0.000001') < needed_usdc:
                return first

            with d._use_key(enc_blob, wallet) as private_key:
                _gasless_usdc_to_sol(d, private_key, needed_usdc)

            remaining = (ceiling - needed_usdc).quantize(
                Decimal('0.000001'), rounding=ROUND_DOWN)
            if remaining < minimum_buy:
                return first

            d.add_user_log(
                wallet,
                f'[bridge] Used ${float(needed_usdc):.2f} of your USDC budget '
                f'to fund Solana network gas; continuing {dest_chain} buy automatically.'
            )
            return original(user_id, wallet, evm_address, dest_chain,
                            token_address, float(remaining))
        except Exception as exc:
            # Keep the original precise bridge refusal if Jupiter cannot supply
            # a gasless bootstrap. Never fall back to platform-paid SOL.
            try:
                d.add_user_log(wallet, '[bridge] Gasless Solana gas bootstrap unavailable: '
                               + d._redact_keys(str(exc))[:220])
            except Exception:
                pass
            return first

    d._maybe_start_auto_bridge_for_buy = auto_bridge
