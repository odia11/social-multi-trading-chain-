"""Gasless Solana USDC BUY adapter using Jupiter Ultra order/execute.

The amount passed to this adapter is an ALL-IN ceiling: Jupiter receives that
exact USDC input amount and may recover its gasless/network costs and an
optional OrcAgent integrator fee from inside the swap. OrcAgent never adds SOL,
never adds a fee on top, and never uses its own sponsor wallet.

Set JUPITER_REFERRAL_ACCOUNT to OrcAgent's Jupiter Ultra referral account to
collect the existing OrcAgent transaction fee atomically inside the order.
The configured FEE_RATE_TXN is translated to referralFee bps (0.75% -> 75).
If no referral account is configured, trading keeps working exactly as before;
the adapter marks the fee as not bundled so accounting never books revenue
that was not actually collected.
"""
from __future__ import annotations

import base64
import os
import time
from decimal import Decimal

import requests
from solders.keypair import Keypair
from solders.message import to_bytes_versioned
from solders.transaction import VersionedTransaction

_API = 'https://api.jup.ag/ultra/v1'
_USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
_GASLESS_SOL_THRESHOLD = 0.01


def _api_key() -> str:
    return (os.getenv('JUPITER_API_KEY', '') or '').strip()


def _referral_account() -> str:
    return (os.getenv('JUPITER_REFERRAL_ACCOUNT', '') or '').strip()


def _referral_fee_bps(d) -> int:
    rate = Decimal(str(getattr(d, 'FEE_RATE_TXN', '0') or '0'))
    bps = int((rate * Decimal('10000')).to_integral_value())
    if bps and not 50 <= bps <= 255:
        raise RuntimeError(
            f'OrcAgent Solana fee is {bps} bps, but Jupiter Ultra integrator fees '
            'must be between 50 and 255 bps')
    return bps


def _headers():
    key = _api_key()
    if not key:
        raise RuntimeError('JUPITER_API_KEY is not configured')
    return {'x-api-key': key, 'Accept': 'application/json',
            'Content-Type': 'application/json'}


def _rpc_url(d):
    return (getattr(d, 'SOLANA_RPC_URL', '') or
            os.getenv('SOLANA_RPC_URL', '') or
            'https://api.mainnet-beta.solana.com')


def _rpc(d, method, params):
    r = requests.post(_rpc_url(d), json={
        'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params,
    }, timeout=12)
    r.raise_for_status()
    data = r.json()
    if data.get('error'):
        raise RuntimeError(str(data['error'])[:240])
    return data.get('result')


def _sol_balance(d, address: str) -> float:
    result = _rpc(d, 'getBalance', [address, {'commitment': 'confirmed'}]) or {}
    return float(result.get('value') or 0) / 1_000_000_000


def _token_decimals(d, mint: str) -> int:
    result = _rpc(d, 'getTokenSupply', [mint]) or {}
    return int((result.get('value') or {}).get('decimals'))


def _sign_for_taker(private_key: str, tx_b64: str) -> str:
    """Add only the user's signature and preserve any Jupiter payer signature."""
    kp = Keypair.from_base58_string(private_key)
    tx = VersionedTransaction.from_bytes(base64.b64decode(tx_b64))
    signatures = list(tx.signatures)
    required = int(tx.message.header.num_required_signatures)
    signer_keys = list(tx.message.account_keys)[:required]
    try:
        index = next(i for i, key in enumerate(signer_keys) if key == kp.pubkey())
    except StopIteration:
        raise RuntimeError('Jupiter transaction does not list the trading wallet as a signer')
    signatures[index] = kp.sign_message(to_bytes_versioned(tx.message))
    signed = VersionedTransaction.populate(tx.message, signatures)
    return base64.b64encode(bytes(signed)).decode()


def _order(d, wallet: str, mint: str, amount_usdc: str):
    amount = Decimal(str(amount_usdc))
    if amount <= 0:
        raise RuntimeError('USDC amount must be greater than zero')
    raw = amount * Decimal(1_000_000)
    if raw != raw.to_integral_value():
        raise RuntimeError('USDC amount has more than 6 decimal places')

    params = {
        'inputMint': _USDC,
        'outputMint': mint,
        'amount': str(int(raw)),
        'taker': wallet,
    }

    referral = _referral_account()
    fee_bps = _referral_fee_bps(d)
    if referral and fee_bps:
        # Jupiter Ultra takes the integrator fee from inside the exact input
        # order, so amount remains the user's absolute spend ceiling.
        params['referralAccount'] = referral
        params['referralFee'] = str(fee_bps)

    r = requests.get(_API + '/order', params=params, headers=_headers(), timeout=20)
    try:
        data = r.json()
    except Exception:
        raise RuntimeError(f'Jupiter order returned HTTP {r.status_code} with non-JSON response')
    if not r.ok:
        raise RuntimeError(str(data.get('error') or data.get('message') or data)[:300])
    if not data.get('transaction'):
        code = data.get('errorCode')
        message = data.get('errorMessage') or data.get('error') or 'Jupiter returned no executable transaction'
        if code == 3:
            raise RuntimeError(
                "This Solana buy is below Jupiter's current gasless minimum. "
                'Increase the USDC amount; OrcAgent will not ask for SOL or subsidize the trade.')
        raise RuntimeError(str(message)[:300])

    # If a referral fee was requested, only call it bundled when Jupiter's
    # response proves that it was actually applied. Missing referral token
    # accounts may otherwise allow the swap while collecting no integrator fee.
    applied_fee_bps = int(data.get('feeBps') or 0)
    platform_fee = data.get('platformFee') or {}
    fee_applied = bool(referral and fee_bps and applied_fee_bps >= fee_bps
                       and int(platform_fee.get('amount') or 0) > 0)
    data['_orcagent_fee_requested_bps'] = fee_bps if referral else 0
    data['_orcagent_fee_applied'] = fee_applied

    # A low/zero-SOL wallet must receive a genuinely gasless order. Never
    # silently fall back to a transaction paid by OrcAgent or requiring SOL.
    try:
        low_sol = _sol_balance(d, wallet) < _GASLESS_SOL_THRESHOLD
    except Exception:
        low_sol = False
    if low_sol and not bool(data.get('gasless')):
        raise RuntimeError(
            'Jupiter did not provide a gasless route for this low-SOL wallet. '
            'No SOL will be requested or paid by OrcAgent.')
    return data


def _execute(order: dict, signed_tx: str):
    payload = {'signedTransaction': signed_tx, 'requestId': order.get('requestId')}
    if not payload['requestId']:
        raise RuntimeError('Jupiter order returned no requestId')

    # Re-submitting the same signed transaction/requestId is idempotent. A
    # short retry window handles transient execute timeouts without ever
    # creating a second swap/signature.
    deadline = time.time() + 115
    last_error = ''
    while time.time() < deadline:
        try:
            r = requests.post(_API + '/execute', json=payload, headers=_headers(), timeout=25)
            data = r.json()
            if r.ok and str(data.get('status') or '').lower() == 'success':
                sig = data.get('signature')
                if not sig:
                    raise RuntimeError('Jupiter reported success without a transaction signature')
                return sig, data
            code = data.get('code')
            last_error = str(data.get('error') or data.get('message') or data.get('status') or code or 'execute failed')[:300]
            if code not in (-1000, -1005, -1006, None):
                break
        except requests.RequestException as exc:
            last_error = str(exc)[:300]
        except ValueError:
            last_error = 'Jupiter execute returned a non-JSON response'
        time.sleep(2)
    raise RuntimeError(last_error or 'Jupiter gasless execution did not confirm')


def install(d):
    original = d._execute_user_swap_ex

    def execute_user_swap_ex(wallet: str, private_key: str, action: str, mint: str,
                             amount_str: str, base: str = 'SOL', capture: dict = None):
        # Only USDC-funded BUYs use Ultra gasless. If no API key is configured,
        # preserve the legacy path instead of breaking deployment startup.
        if str(action).lower() != 'buy' or str(base).upper() != 'USDC' or not _api_key():
            return original(wallet, private_key, action, mint, amount_str, base, capture)
        try:
            kp = Keypair.from_base58_string(private_key)
            trading_address = str(kp.pubkey())
            order = _order(d, trading_address, mint, amount_str)
            signed = _sign_for_taker(private_key, order['transaction'])
            signature, result = _execute(order, signed)
            decimals = _token_decimals(d, mint)
            raw_out = result.get('outputAmountResult') or order.get('outAmount') or 0
            token_amount = float(Decimal(str(raw_out)) / (Decimal(10) ** decimals))
            if capture is not None:
                capture['gasless'] = bool(order.get('gasless'))
                # The legacy caller uses this boolean to decide whether it may
                # record a bundled fee. Only say yes when Jupiter proved it.
                capture['fee_bundled'] = bool(order.get('_orcagent_fee_applied'))
                capture['fee_bps'] = int(order.get('_orcagent_fee_requested_bps') or 0)
                capture['fee_mint'] = order.get('feeMint') or ''
                capture['router'] = order.get('router')
            # Ultra ExactIn spends exactly amount_str. Gasless and integrator
            # costs are recovered inside that amount, never on top of it.
            return True, signature, '', token_amount, float(Decimal(str(amount_str)))
        except Exception as exc:
            return False, '', d._redact_keys(str(exc))[:500], 0.0, 0.0

    d._execute_user_swap_ex = execute_user_swap_ex
