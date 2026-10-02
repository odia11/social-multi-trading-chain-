"""Jupiter-only helpers for Solana USDC -> SOL Ultra orders."""
from decimal import Decimal, ROUND_DOWN

import requests
from solders.keypair import Keypair

import solana_gasless_trading as jup

_SOL_MINT = 'So11111111111111111111111111111111111111112'
_LAMPORTS_PER_SOL = Decimal('1000000000')
_Q6 = Decimal('0.000001')


def _q6(value) -> Decimal:
    return Decimal(str(value)).quantize(_Q6, rounding=ROUND_DOWN)


def _gasless_order(private_key: str, amount_usdc: Decimal, require_gasless: bool = True):
    amount_usdc = _q6(amount_usdc)
    if amount_usdc <= 0:
        raise RuntimeError('swap amount must be positive')
    kp = Keypair.from_base58_string(private_key)
    params = {
        'inputMint': jup._USDC,
        'outputMint': _SOL_MINT,
        'amount': str(int(amount_usdc * Decimal(1_000_000))),
        'taker': str(kp.pubkey()),
    }
    r = requests.get(jup._API + '/order', params=params, headers=jup._headers(), timeout=20)
    try:
        order = r.json()
    except Exception:
        raise RuntimeError(f'Jupiter returned HTTP {r.status_code} with non-JSON response')
    if not r.ok:
        reason = order.get('error') or order.get('errorMessage') or order.get('message') or order
        raise RuntimeError(f'Jupiter order failed (HTTP {r.status_code}): {reason}')
    if not order.get('transaction'):
        raise RuntimeError(str(order.get('errorMessage') or order.get('error')
                               or 'Jupiter returned no executable transaction')[:300])
    if require_gasless and not bool(order.get('gasless')):
        raise RuntimeError('Jupiter did not provide a gasless USDC -> SOL route')
    try:
        out_raw = int(order.get('outAmount') or 0)
    except Exception:
        out_raw = 0
    if out_raw <= 0:
        raise RuntimeError('Jupiter USDC -> SOL quote returned no SOL output')
    return order, Decimal(out_raw) / _LAMPORTS_PER_SOL


def _execute_order(private_key: str, order: dict):
    signed = jup._sign_for_taker(private_key, order['transaction'])
    return jup._execute(order, signed)
