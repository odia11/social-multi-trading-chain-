"""0x Gasless v2 adapter for BNB Chain USDC-funded BUYs.

Product rule: the amount a user enters is the maximum amount of USDC they
spend. They do not need to pre-fund BNB and OrcAgent does not fund BNB for
them. 0x's relayer pays native gas and bills that gas in the sell token
(Binance-Peg USDC), while OrcAgent's platform fee is included in the same
Gasless order via swapFeeBps.

This adapter is intentionally BSC BUY-only. Sells, withdrawals and arbitrary
ERC20 sends still use the normal on-chain path because a random token cannot
be assumed to support a gasless permit.
"""
from __future__ import annotations

import inspect
import os
import sqlite3
import time
from decimal import Decimal

import requests
from eth_account import Account

_API = 'https://api.0x.org'
_HEADERS_VERSION = 'v2'
_BSC = 'bsc'
_BSC_CHAIN_ID = 56
_STATUS_TIMEOUT = 75


def _is_buy_context() -> bool:
    """True only while the existing code is arranging/executing a BUY.

    _ensure_evm_gas() has no action argument and is also used for withdrawals
    and sells, so globally bypassing it on BSC would strand those operations.
    Keep the exception narrowly scoped to call stacks that are buying.
    """
    frame = inspect.currentframe()
    try:
        for _ in range(18):
            if frame is None:
                break
            name = frame.f_code.co_name
            if name in {
                '_evm_buy_flow', 'api_trade_execute', '_execute_auto_buy_after_bridge',
                '_execute_cross_chain_bridge', '_buy_and_get_realized_evm',
                '_execute_copy_trade', '_copy_execute_buy',
            } or ('buy' in name.lower() and 'sell' not in name.lower()):
                return True
            frame = frame.f_back
    finally:
        del frame
    return False


def _api_headers(d):
    key = (getattr(d, 'ZEROX_API_KEY', '') or os.getenv('ZEROX_API_KEY', '')).strip()
    if not key:
        raise RuntimeError('ZEROX_API_KEY is not configured')
    return {'0x-api-key': key, '0x-version': _HEADERS_VERSION,
            'Content-Type': 'application/json'}


def _json_response(resp, label):
    try:
        data = resp.json()
    except Exception:
        raise RuntimeError(f'{label} returned HTTP {resp.status_code} with a non-JSON response')
    if not resp.ok:
        reason = data.get('reason') or data.get('message') or data.get('name') or str(data)[:240]
        raise RuntimeError(f'{label} failed (HTTP {resp.status_code}): {reason}')
    return data


def _split_signature(signed):
    return {
        'r': '0x' + int(signed.r).to_bytes(32, 'big').hex(),
        's': '0x' + int(signed.s).to_bytes(32, 'big').hex(),
        'v': int(signed.v),
        'signatureType': 2,
    }


def _sign_eip712(private_key: str, obj: dict):
    eip = (obj or {}).get('eip712') or {}
    full = {
        'types': eip.get('types') or {},
        'primaryType': eip.get('primaryType'),
        'domain': eip.get('domain') or {},
        'message': eip.get('message') or {},
    }
    if not full['types'] or not full['primaryType']:
        raise RuntimeError('0x gasless quote did not contain valid EIP-712 signing data')
    return _split_signature(Account.sign_typed_data(private_key, full_message=full))


def _fee_recipient(d):
    addr = ''
    try:
        addr = (d._evm_fee_recipient(_BSC) or '').strip()
    except Exception:
        addr = ''
    if not addr or not addr.startswith('0x') or len(addr) != 42:
        raise RuntimeError('EVM fee wallet is not configured; refusing to create a trade with unaccounted platform fees')
    return addr


def _gasless_quote(d, private_key: str, buy_token: str, amount_usdc: str):
    chain = d.te_registry.get_chain(_BSC)
    stable = chain.stable
    amount = Decimal(str(amount_usdc))
    if amount <= 0:
        raise RuntimeError('USDC amount must be greater than zero')
    sell_raw = d.te_registry.to_raw(amount, stable)
    taker = Account.from_key(private_key).address
    fee_bps = int((Decimal(str(d.FEE_RATE_TXN)) * Decimal('10000')).to_integral_value())
    params = {
        'chainId': str(_BSC_CHAIN_ID),
        'sellToken': stable.address,
        'buyToken': buy_token,
        'sellAmount': str(sell_raw),
        'taker': taker,
        'swapFeeRecipient': _fee_recipient(d),
        'swapFeeBps': str(fee_bps),
        'swapFeeToken': stable.address,
    }
    r = requests.get(_API + '/gasless/quote', params=params,
                     headers=_api_headers(d), timeout=15)
    q = _json_response(r, '0x gasless quote')
    if q.get('liquidityAvailable') is False:
        raise RuntimeError('No gasless BSC liquidity route is available for this token')
    if not q.get('trade'):
        raise RuntimeError('0x gasless quote contained no executable trade')
    return q


def _submit_and_wait(d, private_key: str, quote: dict):
    issues = quote.get('issues') or {}
    allowance_needed = issues.get('allowance') is not None
    approval = quote.get('approval')
    approval_submit = None
    if allowance_needed:
        if not approval:
            raise RuntimeError('This USDC approval cannot be completed gaslessly; no BNB will be requested or spent')
        approval_submit = {
            'type': approval.get('type'),
            'eip712': approval.get('eip712'),
            'signature': _sign_eip712(private_key, approval),
        }

    trade = quote['trade']
    body = {
        'trade': {
            'type': trade.get('type'),
            'eip712': trade.get('eip712'),
            'signature': _sign_eip712(private_key, trade),
        },
        'chainId': _BSC_CHAIN_ID,
    }
    if approval_submit:
        body['approval'] = approval_submit

    r = requests.post(_API + '/gasless/submit', json=body,
                      headers=_api_headers(d), timeout=15)
    out = _json_response(r, '0x gasless submit')
    trade_hash = out.get('tradeHash')
    if not trade_hash:
        raise RuntimeError('0x gasless submit returned no tradeHash')

    deadline = time.time() + _STATUS_TIMEOUT
    last = ''
    while time.time() < deadline:
        sr = requests.get(_API + f'/gasless/status/{trade_hash}',
                          params={'chainId': str(_BSC_CHAIN_ID)},
                          headers=_api_headers(d), timeout=12)
        status = _json_response(sr, '0x gasless status')
        last = str(status.get('status') or '').lower()
        if last == 'confirmed':
            txs = status.get('transactions') or []
            tx_hash = (txs[-1].get('hash') if txs and isinstance(txs[-1], dict) else None) \
                      or status.get('transactionHash') or trade_hash
            return tx_hash
        if last in {'failed', 'reverted', 'cancelled', 'canceled'}:
            reason = status.get('reason') or status.get('error') or last
            raise RuntimeError(f'0x gasless trade {last}: {reason}')
        time.sleep(2)
    raise RuntimeError(f'0x gasless trade was submitted but not confirmed within {_STATUS_TIMEOUT}s (last status: {last or "unknown"})')


def _record_bundled_fee(d, wallet: str, symbol: str, purchase_usdc: float,
                        kind: str, chain: str, tx_hash: str, gross_profit: float = 0.0):
    """Record a platform fee already collected inside the 0x gasless order.

    No second ERC20 transfer is sent: that would require BNB and would also
    double-charge the user. Referral accounting mirrors dashboard's existing
    EVM fee path.
    """
    fee = round(float(purchase_usdc) * float(d.FEE_RATE_TXN), 6)
    if fee <= 0:
        return
    recipient = _fee_recipient(d)
    conn = sqlite3.connect(d.DB_FILE)
    try:
        conn.execute('PRAGMA busy_timeout=3000')
        conn.execute(
            'INSERT INTO fees (user_wallet, token, gross_profit, fee_amount, fee_tx, status, kind, chain, recipient) '
            'VALUES (?,?,?,?,?,?,?,?,?)',
            (wallet, symbol, float(gross_profit or 0), fee,
             '0x-gasless:' + str(tx_hash), 'ok', kind, chain, recipient))
        row = conn.execute('SELECT referred_by FROM users WHERE wallet_address=?', (wallet,)).fetchone()
        if row and row[0]:
            referrer = row[0]
            earned = round(fee * 0.20, 6)
            conn.execute(
                'INSERT INTO referral_earnings '
                '(referrer_wallet, referred_wallet, trade_fee_sol, earned_sol, chain) VALUES (?,?,?,?,?)',
                (referrer, wallet, fee, earned, chain))
            conn.execute('UPDATE users SET referral_balance = referral_balance + ? WHERE wallet_address=?',
                         (earned, referrer))
        conn.commit()
    finally:
        conn.close()


def install(d):
    original_execute = d._execute_evm_swap
    original_ensure = d._ensure_evm_gas
    original_fee = d._charge_evm_txn_fee
    state = __import__('threading').local()

    def ensure_gas(user_id, wallet, private_key, evm_address, chain,
                   auto_buy_token_address=None, auto_buy_requested_usdc=None):
        if chain == _BSC and _is_buy_context():
            return True, '', None
        return original_ensure(user_id, wallet, private_key, evm_address, chain,
                               auto_buy_token_address, auto_buy_requested_usdc)

    def execute(wallet, private_key, action, token_address, amount_str, chain='bsc'):
        if chain != _BSC or str(action).lower() != 'buy':
            return original_execute(wallet, private_key, action, token_address, amount_str, chain)
        try:
            quote = _gasless_quote(d, private_key, token_address, amount_str)
            tx_hash = _submit_and_wait(d, private_key, quote)
            state.last_bsc_buy = {'tx_hash': tx_hash, 'at': time.time()}
            return True, '', tx_hash
        except Exception as exc:
            return False, d._redact_keys(str(exc))[:500], ''

    def charge_fee(private_key, wallet, user_id, symbol, usdc_amount, kind,
                   chain='bsc', trade_ts=None, gross_profit=0.0):
        marker = getattr(state, 'last_bsc_buy', None)
        if chain == _BSC and str(kind).lower() == 'buy' and marker and time.time() - marker['at'] < 120:
            try:
                _record_bundled_fee(d, wallet, symbol, usdc_amount, kind, chain,
                                    marker['tx_hash'], gross_profit)
            finally:
                state.last_bsc_buy = None
            return
        return original_fee(private_key, wallet, user_id, symbol, usdc_amount, kind,
                            chain, trade_ts, gross_profit)

    d._ensure_evm_gas = ensure_gas
    d._execute_evm_swap = execute
    d._charge_evm_txn_fee = charge_fee
