"""0x Gasless v2 adapter for every EVM BUY OrcAgent supports.

Product rule: a user may hold only the chain's dollar asset (USDC, or USDG
on Robinhood Chain) and still BUY with zero native gas token. OrcAgent does
not subsidize gas. 0x relays the signed EIP-712 order and recovers network
costs inside the user's sell-token-funded order; OrcAgent's platform fee is
embedded in that same order via swapFeeBps.

The filename is kept for backwards compatibility with app_entry.py and older
deployments, but the adapter is no longer BSC-specific. It derives chain id,
stable token and decimals from OrcAgent's central registry for BSC, Base,
Arbitrum, Polygon and Robinhood Chain.

Sells, withdrawals and arbitrary ERC20 transfers intentionally keep the normal
on-chain gas path: a random token cannot be assumed to support gasless permit.
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
_STATUS_TIMEOUT = 75


def _is_buy_context() -> bool:
    """True only while existing code is arranging/executing a BUY."""
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


def _is_sell_context() -> bool:
    """True while an OrcAgent manual/bot EVM exit is being executed."""
    frame = inspect.currentframe()
    try:
        for _ in range(18):
            if frame is None:
                break
            name = frame.f_code.co_name
            if name in {
                '_evm_sell_flow', '_bot_execute_exit', '_sell_and_get_realized_evm',
                '_execute_copy_sell', '_copy_execute_sell',
            } or ('sell' in name.lower() and 'buy' not in name.lower()):
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


def _evm_chain(d, chain_name: str):
    chain = d.te_registry.get_chain(chain_name)
    if chain.kind != 'evm' or not chain.chain_id:
        raise RuntimeError(f'{chain_name} is not an EVM gasless chain')
    return chain


def _stable_decimals(d, chain_name: str, stable) -> int:
    """Use verified registry decimals; read the deployed ERC20 when unknown."""
    if stable.decimals is not None:
        return int(stable.decimals)
    w3 = d._get_web3(chain_name)
    abi = [{
        'constant': True, 'inputs': [], 'name': 'decimals',
        'outputs': [{'name': '', 'type': 'uint8'}], 'type': 'function'
    }]
    contract = w3.eth.contract(address=w3.to_checksum_address(stable.address), abi=abi)
    decimals = int(contract.functions.decimals().call())
    if decimals < 0 or decimals > 36:
        raise RuntimeError(f'implausible {stable.symbol} decimals on {chain_name}: {decimals}')
    try:
        d.te_registry.verify_decimals(chain_name, stable.address, decimals, source='on-chain contract')
    except Exception:
        pass
    return decimals


def _to_stable_raw(d, chain_name: str, amount: Decimal, stable) -> int:
    decimals = _stable_decimals(d, chain_name, stable)
    scaled = amount * (Decimal(10) ** decimals)
    if scaled != scaled.to_integral_value():
        raise RuntimeError(
            f'{amount} has more precision than {stable.symbol} on {chain_name} can represent')
    return int(scaled)


def _fee_recipient(d, chain_name: str):
    addr = ''
    try:
        addr = (d._evm_fee_recipient(chain_name) or '').strip()
    except Exception:
        addr = ''
    if not addr or not addr.startswith('0x') or len(addr) != 42:
        raise RuntimeError(
            f'EVM fee wallet is not configured for {chain_name}; refusing a trade with unaccounted platform fees')
    return addr


def _gasless_quote(d, private_key: str, buy_token: str, amount_usdc: str, chain_name: str):
    chain = _evm_chain(d, chain_name)
    stable = chain.stable
    amount = Decimal(str(amount_usdc))
    if amount <= 0:
        raise RuntimeError(f'{stable.symbol} amount must be greater than zero')
    sell_raw = _to_stable_raw(d, chain_name, amount, stable)
    taker = Account.from_key(private_key).address
    fee_bps = int((Decimal(str(d.FEE_RATE_TXN)) * Decimal('10000')).to_integral_value())
    params = {
        'chainId': str(chain.chain_id),
        'sellToken': stable.address,
        'buyToken': buy_token,
        'sellAmount': str(sell_raw),
        'taker': taker,
        'swapFeeRecipient': _fee_recipient(d, chain_name),
        'swapFeeBps': str(fee_bps),
        'swapFeeToken': stable.address,
    }
    r = requests.get(_API + '/gasless/quote', params=params,
                     headers=_api_headers(d), timeout=15)
    q = _json_response(r, f'0x gasless quote ({chain.display_name})')
    if q.get('liquidityAvailable') is False:
        raise RuntimeError(f'No gasless {chain.display_name} liquidity route is available for this token')
    if not q.get('trade'):
        raise RuntimeError(f'0x gasless quote for {chain.display_name} contained no executable trade')
    return q, chain


def _erc20_amount_raw(d, chain_name: str, token_address: str, amount) -> int:
    """Convert a human ERC20 amount to raw units without float rounding."""
    w3 = d._get_web3(chain_name)
    abi = [{
        'constant': True, 'inputs': [], 'name': 'decimals',
        'outputs': [{'name': '', 'type': 'uint8'}], 'type': 'function'
    }]
    contract = w3.eth.contract(
        address=w3.to_checksum_address(token_address), abi=abi)
    decimals = int(contract.functions.decimals().call())
    if decimals < 0 or decimals > 36:
        raise RuntimeError(f'implausible token decimals on {chain_name}: {decimals}')
    raw = Decimal(str(amount)) * (Decimal(10) ** decimals)
    # Tracked bot quantities may contain more precision than the token can
    # represent. Floor to what the chain can actually transfer, never round up
    # and accidentally ask 0x to sell more than the wallet owns.
    return int(raw)


def _gasless_sell_quote(d, private_key: str, sell_token: str,
                        amount_token, chain_name: str):
    """Gasless ERC20 -> chain stablecoin quote for an exit."""
    chain = _evm_chain(d, chain_name)
    sell_raw = _erc20_amount_raw(
        d, chain_name, sell_token, amount_token)
    if sell_raw <= 0:
        raise RuntimeError('Token sell amount must be greater than zero')
    taker = Account.from_key(private_key).address
    fee_bps = int((Decimal(str(d.FEE_RATE_TXN)) *
                   Decimal('10000')).to_integral_value())
    params = {
        'chainId': str(chain.chain_id),
        'sellToken': sell_token,
        'buyToken': chain.stable.address,
        'sellAmount': str(sell_raw),
        'taker': taker,
        # Fee comes from the stablecoin proceeds, not as a second transfer.
        'swapFeeRecipient': _fee_recipient(d, chain_name),
        'swapFeeBps': str(fee_bps),
        'swapFeeToken': chain.stable.address,
    }
    r = requests.get(_API + '/gasless/quote', params=params,
                     headers=_api_headers(d), timeout=15)
    q = _json_response(r, f'0x gasless sell quote ({chain.display_name})')
    if q.get('liquidityAvailable') is False:
        raise RuntimeError(
            f'No gasless {chain.display_name} sell route is available for this token')
    if not q.get('trade'):
        raise RuntimeError(
            f'0x gasless sell quote for {chain.display_name} contained no executable trade')
    return q, chain


def _gasless_native_topup(d, private_key: str, chain_name: str) -> str:
    """Use the user's own stablecoin to obtain native gas without pre-funding.

    This is only a fallback for ERC20s whose approval cannot itself be signed
    gaslessly. OrcAgent fronts nothing: 0x relays a stablecoin-funded swap and
    the resulting native coin lands in the same user trading wallet.
    """
    chain = _evm_chain(d, chain_name)
    taker = Account.from_key(private_key).address
    available = Decimal(str(d.get_evm_usdc_balance(taker, chain_name)))
    configured = Decimal(str(getattr(d, 'GAS_TOPUP_USDC_AMOUNT', 2.0)))
    amount = min(available, configured)
    # 0x documents roughly a $1 practical Gasless minimum on non-mainnet
    # chains. Below this, pretending a top-up can be created just delays the
    # exit; fail cleanly and keep the position open instead.
    if amount < Decimal('1'):
        raise RuntimeError(
            f'Not enough {chain.stable.symbol} remains to create gas for this sell')
    sell_raw = _to_stable_raw(d, chain_name, amount, chain.stable)
    params = {
        'chainId': str(chain.chain_id),
        'sellToken': chain.stable.address,
        'buyToken': '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE',
        'sellAmount': str(sell_raw),
        'taker': taker,
    }
    r = requests.get(_API + '/gasless/quote', params=params,
                     headers=_api_headers(d), timeout=15)
    q = _json_response(r, f'0x gasless gas top-up ({chain.display_name})')
    if q.get('liquidityAvailable') is False or not q.get('trade'):
        raise RuntimeError(
            f'No gasless {chain.stable.symbol}-to-{chain.native.symbol} route is available')
    # Deliberately no OrcAgent platform fee on this internal gas conversion.
    return _submit_and_wait(d, private_key, q, chain)


def _submit_and_wait(d, private_key: str, quote: dict, chain) -> str:
    issues = quote.get('issues') or {}
    allowance_needed = issues.get('allowance') is not None
    approval = quote.get('approval')
    approval_submit = None
    if allowance_needed:
        if not approval:
            raise RuntimeError(
                f'This {chain.stable.symbol} approval cannot be completed gaslessly on '
                f'{chain.display_name}; no {chain.native.symbol} will be requested or spent')
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
        'chainId': int(chain.chain_id),
    }
    if approval_submit:
        body['approval'] = approval_submit

    r = requests.post(_API + '/gasless/submit', json=body,
                      headers=_api_headers(d), timeout=15)
    out = _json_response(r, f'0x gasless submit ({chain.display_name})')
    trade_hash = out.get('tradeHash')
    if not trade_hash:
        raise RuntimeError('0x gasless submit returned no tradeHash')

    deadline = time.time() + _STATUS_TIMEOUT
    last = ''
    while time.time() < deadline:
        sr = requests.get(_API + f'/gasless/status/{trade_hash}',
                          params={'chainId': str(chain.chain_id)},
                          headers=_api_headers(d), timeout=12)
        status = _json_response(sr, f'0x gasless status ({chain.display_name})')
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
    raise RuntimeError(
        f'0x gasless trade was submitted but not confirmed within {_STATUS_TIMEOUT}s '
        f'(last status: {last or "unknown"})')


def _record_bundled_fee(d, wallet: str, symbol: str, purchase_usdc: float,
                        kind: str, chain: str, tx_hash: str, gross_profit: float = 0.0):
    """Record the platform fee already collected inside the 0x order."""
    fee = round(float(purchase_usdc) * float(d.FEE_RATE_TXN), 6)
    if fee <= 0:
        return
    recipient = _fee_recipient(d, chain)
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

    def _supported(chain_name: str) -> bool:
        try:
            return d.te_registry.get_chain(chain_name).kind == 'evm'
        except Exception:
            return False

    def ensure_gas(user_id, wallet, private_key, evm_address, chain,
                   auto_buy_token_address=None, auto_buy_requested_usdc=None):
        # Every supported EVM BUY is relayed. EVM SELLs now try Gasless first
        # as well. Therefore native BNB/ETH/POL must not block the caller before
        # execute() gets a chance to use the relay. If a token cannot be
        # approved gaslessly, execute() creates native gas from this user's own
        # stablecoin and then falls back to the mature signed sell path.
        if _supported(chain) and (_is_buy_context() or _is_sell_context()):
            return True, '', None
        return original_ensure(user_id, wallet, private_key, evm_address, chain,
                               auto_buy_token_address, auto_buy_requested_usdc)

    def execute(wallet, private_key, action, token_address, amount_str, chain='bsc'):
        action = str(action).lower()
        if not _supported(chain) or action not in {'buy', 'sell'}:
            return original_execute(
                wallet, private_key, action, token_address, amount_str, chain)
        if action == 'buy':
            try:
                quote, meta = _gasless_quote(
                    d, private_key, token_address, amount_str, chain)
                tx_hash = _submit_and_wait(d, private_key, quote, meta)
                state.last_evm_buy = {
                    'chain': chain, 'tx_hash': tx_hash, 'at': time.time()}
                return True, '', tx_hash
            except Exception as exc:
                return False, d._redact_keys(str(exc))[:500], ''

        # SELL: Gasless API can relay sales of non-native ERC20 tokens. This is
        # the preferred path because TP/SL must still be able to close a
        # position when the user holds zero BNB/ETH/POL.
        gasless_error = None
        try:
            quote, meta = _gasless_sell_quote(
                d, private_key, token_address, amount_str, chain)
            tx_hash = _submit_and_wait(d, private_key, quote, meta)
            return True, '', tx_hash
        except Exception as exc:
            gasless_error = d._redact_keys(str(exc))[:350]

        # Some meme tokens do not implement EIP-2612. 0x can relay their swap
        # only after an ordinary allowance exists. Instead of asking the user
        # to manually deposit gas, buy a small amount of native gas using the
        # user's own remaining USDC/USDG through a separate gasless swap, then
        # use the existing approval+sell implementation. OrcAgent contributes
        # no funds and takes no platform fee on this gas conversion.
        try:
            _gasless_native_topup(d, private_key, chain)
            return original_execute(
                wallet, private_key, 'sell', token_address, amount_str, chain)
        except Exception as fallback_exc:
            fallback_error = d._redact_keys(str(fallback_exc))[:350]
            return False, (
                'Gasless sell could not be completed'
                + (f': {gasless_error}' if gasless_error else '')
                + f'; automatic gas setup also failed: {fallback_error}'
            )[:700], ''

    def charge_fee(private_key, wallet, user_id, symbol, usdc_amount, kind,
                   chain='bsc', trade_ts=None, gross_profit=0.0):
        marker = getattr(state, 'last_evm_buy', None)
        if (_supported(chain) and str(kind).lower() == 'buy' and marker
                and marker.get('chain') == chain and time.time() - marker['at'] < 120):
            try:
                _record_bundled_fee(d, wallet, symbol, usdc_amount, kind, chain,
                                    marker['tx_hash'], gross_profit)
            finally:
                state.last_evm_buy = None
            return
        return original_fee(private_key, wallet, user_id, symbol, usdc_amount, kind,
                            chain, trade_ts, gross_profit)

    d._ensure_evm_gas = ensure_gas
    d._execute_evm_swap = execute
    d._charge_evm_txn_fee = charge_fee
