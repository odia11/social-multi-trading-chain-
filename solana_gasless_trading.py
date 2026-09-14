"""Gasless Solana USDC BUY adapter using Jupiter's order/execute API.

A trading wallet may hold USDC and zero SOL. Jupiter's automatic gasless
support can pay base/priority fees and account rent, then recover that cost
from the swap itself. OrcAgent does not provide SOL and does not use its own
sponsor wallet.

This adapter only replaces USDC-funded BUY execution. Sells and legacy SOL
trades keep the existing engine. When JUPITER_API_KEY is absent it also keeps
the existing engine, so a deploy cannot silently break trading; production
must configure the key before relying on zero-SOL Solana buys.
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
            raise RuntimeError('This Solana buy is below Jupiter\'s current gasless minimum. Increase the USDC amount; OrcAgent will not ask for SOL or subsidize the trade.')
        raise RuntimeError(str(message)[:300])

    # If this wallet is in the zero/low-SOL case, never accept a transaction
    # that expects the user to pay SOL. Either Jupiter makes it gasless or the
    # order is refused; OrcAgent does not silently fall back to sponsorship.
    try:
        low_sol = _sol_balance(d, wallet) < _GASLESS_SOL_THRESHOLD
    except Exception:
        low_sol = False
    if low_sol and not bool(data.get('gasless')):
        raise RuntimeError('Jupiter did not provide a gasless route for this low-SOL wallet. No SOL will be requested or paid by OrcAgent.')
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
            # Definitive on-chain/business failures should not be retried.
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
        # Jupiter automatic gasless applies to the USDC-funded buy path. If no
        # API key is configured, preserve current behaviour rather than making
        # every Solana trade fail at import/deploy time.
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
                capture['fee_bundled'] = False
                capture['router'] = order.get('router')
            return True, signature, '', token_amount, float(Decimal(str(amount_str)))
        except Exception as exc:
            return False, '', d._redact_keys(str(exc))[:500], 0.0, 0.0

    d._execute_user_swap_ex = execute_user_swap_ex
