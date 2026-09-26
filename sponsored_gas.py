"""Gas the sponsor wallet fronts, paid back by the user in the same trade.

WHY
Every EVM buy first goes through 0x Gasless: the relayer pays the network fee
and takes it out of the order, so nobody fronts anything. Where Gasless cannot
serve the trade -- a chain it does not cover (Robinhood Chain), a token with
no gasless route, a stablecoin whose approval cannot be signed gaslessly --
a wallet that holds only USDC/USDG and no ETH could not trade at all. For the
user that looks like "buying does not work on this chain".

WHAT THIS DOES
When (and only when) Gasless could not even submit the trade, the sponsor
wallet sends the user's trading wallet exactly the native gas the trade needs
(approve + swap + the repayment itself), and the user pays it straight back
in the chain's stablecoin as part of the same trade:

  buy   1. price the swap with the normal 0x route (nothing is sent if there
           is no route or not enough balance);
        2. sponsor sends the missing ETH/BNB/POL;
        3. the user's wallet pays the sponsor back in USDC/USDG -- BEFORE the
           swap, so the sponsor is never left waiting on a swap outcome;
        4. the swap runs for what is left of the amount the user entered.
  sell  the same, except the repayment comes out of the sale proceeds.

The amount the user entered stays the all-in ceiling: the repayment comes out
of it (or out of the gas reserve the trade engine already set aside for it),
never on top. Whatever ETH is left after the trade stays in the user's wallet
-- they paid for it -- and makes the next trade cheaper.

The sponsor is float, not a subsidy: each grant is written to
gas_sponsorships with its dollar value and what was paid back
(trade_engine/subsidy.py reports anything outstanding). A wallet that still
owes a grant pays that first; nothing new is fronted to a wallet whose debt
cannot be settled.

Switch: ORCAGENT_SPONSORED_GAS=0 turns this off. It also needs
GAS_SPONSOR_PRIVATE_KEY and a sponsor wallet holding native gas on the chain.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from decimal import Decimal, ROUND_DOWN, ROUND_UP

from eth_account import Account

# Gasless failures that happened before anything was submitted. Only these
# may fall back to a sponsored trade: a trade that was submitted (or might
# have been) must never be tried a second time.
_NOT_SUBMITTED = (
    'gasless quote', 'no gasless', 'cannot be completed gaslessly',
    'not an evm gasless chain', 'gasless submit', 'contained no executable trade',
)
# A gasless SELL that ran out of every other way to pay for its approval.
_SELL_NEEDS_GAS = ('one-time on-chain approval', 'for gas fees')

GAS_MARGIN = Decimal('1.3')          # over the estimate, for base-fee movement
DEFAULT_SWAP_GAS = 700_000           # when 0x gives no estimate
DEFAULT_TOKEN_TX_GAS = 120_000       # approve / transfer, when estimation fails
MAX_GRANTS_PER_DAY = 30              # per user per chain; each one is repaid
MIN_SWAP_USD = Decimal('0.50')       # below this the trade is not worth the gas
CENT = Decimal('0.01')

PURPOSE_BUY, PURPOSE_SELL = 'sponsored:buy', 'sponsored:sell'

_locks: dict = {}
_locks_guard = threading.Lock()


class SponsorError(Exception):
    """A sponsored trade could not be set up. Nothing was swapped."""


def enabled(d) -> bool:
    if os.getenv('ORCAGENT_SPONSORED_GAS', '1').strip().lower() in ('0', 'false', 'no', 'off'):
        return False
    return bool(getattr(d, 'GAS_SPONSOR_PRIVATE_KEY', '') and sponsor_address(d))


def sponsor_address(d) -> str:
    try:
        return Account.from_key(d.GAS_SPONSOR_PRIVATE_KEY).address
    except Exception:
        return ''


def _lock_for(address: str, chain: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault((address.lower(), chain), threading.Lock())


def _user_id(d, wallet: str):
    conn = sqlite3.connect(d.DB_FILE)
    try:
        row = conn.execute('SELECT id FROM users WHERE wallet_address=?', (wallet,)).fetchone()
        return int(row[0]) if row else None
    finally:
        conn.close()


def _cents_up(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_UP)


# ── debts ───────────────────────────────────────────────────────────────────

def owed(d, user_id: int, chain: str) -> list:
    """[(sponsorship_id, amount_still_owed_usd)] for this user on this chain."""
    conn = sqlite3.connect(d.DB_FILE)
    try:
        rows = conn.execute(
            "SELECT id, COALESCE(amount_usd,0) - COALESCE(recovered_usd,0) FROM gas_sponsorships "
            "WHERE user_id=? AND chain=? AND status='sent' AND trade_id LIKE 'sponsored:%' "
            "AND COALESCE(recovered_usd,0) < COALESCE(amount_usd,0) ORDER BY id",
            (user_id, chain)).fetchall()
    finally:
        conn.close()
    return [(int(r[0]), _cents_up(Decimal(str(r[1])))) for r in rows if r[1] and r[1] > 0]


def _grants_today(d, user_id: int, chain: str) -> int:
    conn = sqlite3.connect(d.DB_FILE)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM gas_sponsorships WHERE user_id=? AND chain=? AND status='sent' "
            "AND trade_id LIKE 'sponsored:%' AND created_at > datetime('now','-1 day')",
            (user_id, chain)).fetchone()[0]
    finally:
        conn.close()


def _record_grant(d, user_id, wallet, chain, to_address, grant_native, usd, tx_hash, purpose) -> int:
    conn = sqlite3.connect(d.DB_FILE)
    try:
        cur = conn.execute(
            'INSERT INTO gas_sponsorships (user_id, wallet, chain, to_address, amount_native, amount_usd, '
            "tx_hash, status, error_msg, trade_id, recovered_usd) VALUES (?,?,?,?,?,?,?,'sent','',?,0)",
            (user_id, wallet, chain, to_address, float(grant_native), float(usd), tx_hash, purpose))
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _mark_repaid(d, ids: list, repay_tx: str):
    conn = sqlite3.connect(d.DB_FILE)
    try:
        for sid in ids:
            conn.execute(
                "UPDATE gas_sponsorships SET recovered_usd=amount_usd, "
                "error_msg=? WHERE id=?", (('repaid ' + repay_tx)[:200], sid))
        conn.commit()
    finally:
        conn.close()


# ── chain pieces ────────────────────────────────────────────────────────────

def _fee_per_gas(d, w3, chain: str) -> int:
    fields = d._evm_tx_fee_fields(w3, chain)
    return int(fields.get('maxFeePerGas') or fields.get('gasPrice') or w3.eth.gas_price)


def _estimate(call, owner: str, default: int) -> int:
    try:
        return int(call.estimate_gas({'from': owner}))
    except Exception:
        return default


def _transfer_gas(w3, frm: str, to: str, value: int) -> int:
    """Gas for a plain native transfer. 21000 on L1s; more on rollups such as
    Robinhood Chain, whose gas figure includes the L1 data cost."""
    try:
        return max(21000, int(int(w3.eth.estimate_gas({'from': frm, 'to': to, 'value': int(value)})) * 1.25))
    except Exception:
        return 100_000


def _send_grant(d, chain: str, to_cs: str, grant_wei: int) -> str:
    """Native transfer sponsor -> user trading wallet. Raises unless confirmed."""
    w3 = d._get_web3(chain)
    sponsor = Account.from_key(d.GAS_SPONSOR_PRIVATE_KEY)
    sponsor_cs = w3.to_checksum_address(sponsor.address)
    native = d.EVM_CHAINS[chain]['native_symbol']
    with d._gas_sponsor_lock:
        fields = d._evm_tx_fee_fields(w3, chain)
        per_gas = int(fields.get('maxFeePerGas') or fields.get('gasPrice'))
        gas = _transfer_gas(w3, sponsor_cs, to_cs, grant_wei)
        if w3.eth.get_balance(sponsor_cs) < grant_wei + gas * per_gas:
            print(f'[sponsored-gas] ⚠ sponsor wallet {sponsor_cs[:10]}... is out of {native} on {chain} '
                  f'-- top it up so {chain} trades keep working', flush=True)
            raise SponsorError(f'sponsor wallet is out of {native} on {chain}')
        tx = {'from': sponsor_cs, 'to': to_cs, 'value': int(grant_wei), 'gas': gas,
              'nonce': w3.eth.get_transaction_count(sponsor_cs),
              'chainId': d.EVM_CHAINS[chain]['chain_id'], **fields}
        signed = sponsor.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
        if receipt.status != 1:
            raise SponsorError('sponsor gas transfer reverted on-chain')
        return tx_hash.hex()


def _plan(d, chain: str, owner_cs: str, gas_units: int) -> tuple:
    """(grant_wei, grant_usd) needed so `owner` can pay for `gas_units`."""
    w3 = d._get_web3(chain)
    per_gas = _fee_per_gas(d, w3, chain)
    need = int(Decimal(gas_units) * GAS_MARGIN) * per_gas
    have = int(w3.eth.get_balance(owner_cs))
    grant = max(0, need - have)
    if grant == 0:
        return 0, Decimal(0)
    price = Decimal(str(d._te_native_price_usd(chain)))
    # The user also pays for the sponsor's own transfer to them.
    sponsor = w3.to_checksum_address(sponsor_address(d))
    wei = Decimal(grant + _transfer_gas(w3, sponsor, owner_cs, grant) * int(w3.eth.gas_price))
    return grant, _cents_up(wei / Decimal(10) ** 18 * price)


def _max_grant_usd() -> Decimal:
    return Decimal(os.getenv('ORCAGENT_SPONSOR_MAX_USD', '1.00'))


def _check_grant(d, user_id, chain, grant_usd: Decimal):
    """Refuse a grant before anything is sent. Raises SponsorError."""
    if grant_usd > _max_grant_usd():
        raise SponsorError(f'network fees on {chain} are unusually high right now (${grant_usd}) '
                           f'— please try again in a minute')
    if _grants_today(d, user_id, chain) >= MAX_GRANTS_PER_DAY:
        raise SponsorError('daily limit for network-fee help reached — please try again tomorrow')


def _send_and_record(d, user_id, wallet, chain, owner_cs, grant_wei, grant_usd, purpose) -> int:
    tx = _send_grant(d, chain, owner_cs, grant_wei)
    native = Decimal(grant_wei) / Decimal(10) ** 18
    sid = _record_grant(d, user_id, wallet, chain, owner_cs, native, grant_usd, tx, purpose)
    print(f'[sponsored-gas] {chain} fronted {native} {d.EVM_CHAINS[chain]["native_symbol"]} '
          f'(${grant_usd}) to {wallet[:8]}... for a {purpose.split(":")[1]} TX:{tx[:18]}...', flush=True)
    return sid


def _front(d, user_id, wallet, chain, owner_cs, gas_units, purpose) -> tuple:
    """Send the gas this trade needs. Returns (sponsorship_id|None, usd)."""
    grant_wei, grant_usd = _plan(d, chain, owner_cs, gas_units)
    if grant_wei == 0:
        return None, Decimal(0)
    _check_grant(d, user_id, chain, grant_usd)
    return _send_and_record(d, user_id, wallet, chain, owner_cs, grant_wei, grant_usd, purpose), grant_usd


def _repay(d, private_key: str, chain: str, ids: list, amount: Decimal) -> str:
    """The user's wallet pays the sponsor back in the chain's stablecoin."""
    if amount <= 0 or not ids:
        return ''
    tx = d._send_evm_usdc_fee(private_key, sponsor_address(d), float(amount), chain)
    _mark_repaid(d, ids, tx)
    print(f'[sponsored-gas] {chain} repaid ${amount} to the sponsor TX:{tx[:18]}...', flush=True)
    return tx


def _stable_decimals(d, w3, chain: str) -> int:
    c = w3.eth.contract(address=w3.to_checksum_address(d.EVM_CHAINS[chain]['usdc']), abi=d._ERC20_MIN_ABI)
    return int(c.functions.decimals().call())


# ── the two trades ──────────────────────────────────────────────────────────

def sponsored_buy(d, raw_execute, wallet, private_key, token_address, amount_str, chain,
                  reserve_usd: Decimal = Decimal(0)) -> tuple:
    user_id = _user_id(d, wallet)
    if not user_id:
        return False, 'User not found', ''
    w3 = d._get_web3(chain)
    owner_cs = w3.to_checksum_address(Account.from_key(private_key).address)
    stable = d.EVM_CHAINS[chain]['usdc']
    sym = d.EVM_CHAINS[chain].get('usdc_symbol', 'USDC')
    amount = Decimal(str(amount_str))

    with _lock_for(owner_cs, chain):
        balance = Decimal(str(d.get_evm_usdc_balance(owner_cs, chain)))
        debts = owed(d, user_id, chain)
        debt = sum((a for _i, a in debts), Decimal(0))
        if balance < amount + debt:
            return False, f'Insufficient {sym} balance', ''

        # 1. Price the real route first: no route, no gas is sent.
        decimals = _stable_decimals(d, w3, chain)
        raw = int(amount * (Decimal(10) ** decimals))
        token_cs = w3.to_checksum_address(token_address)
        try:
            quote = d._get_0x_quote(stable, token_cs, raw, owner_cs, chain, apply_platform_fee=True)
        except Exception as e:
            return False, f'Could not price this trade: {d._redact_keys(str(e))[:160]}', ''
        issues = quote.get('issues') or {}
        if issues.get('balance'):
            return False, f'Insufficient {sym} balance', ''
        txn = quote.get('transaction') or {}
        if not txn and not issues.get('allowance'):
            return False, 'No liquidity route found for this trade', ''
        erc20 = w3.eth.contract(address=w3.to_checksum_address(stable), abi=d._ERC20_FULL_ABI)
        units = int(txn.get('gas') or 0) or DEFAULT_SWAP_GAS
        if issues.get('allowance'):
            units += _estimate(erc20.functions.approve(
                w3.to_checksum_address(issues['allowance'].get('spender') or owner_cs), raw),
                owner_cs, DEFAULT_TOKEN_TX_GAS)
        units += _estimate(erc20.functions.transfer(
            w3.to_checksum_address(sponsor_address(d)), 1), owner_cs, DEFAULT_TOKEN_TX_GAS)

        # 2. Work out the fee and what is left to buy with -- and refuse
        #    BEFORE anything is sent if that does not add up.
        try:
            grant_wei, grant_usd = _plan(d, chain, owner_cs, units)
            if grant_wei:
                _check_grant(d, user_id, chain, grant_usd)
        except SponsorError as e:
            return False, str(e)[:1].upper() + str(e)[1:], ''
        except Exception as e:
            return False, f'Could not price the network fee: {d._redact_keys(str(e))[:120]}', ''
        repay = _cents_up(grant_usd + debt)
        # A gas reserve the caller already set aside (and which is still in
        # the wallet) pays first; only the rest comes out of the purchase.
        from_reserve = min(max(reserve_usd, Decimal(0)), max(balance - amount - debt, Decimal(0)))
        swap = amount - max(repay - debt - from_reserve, Decimal(0))
        swap = swap.quantize(Decimal('0.000001'), rounding=ROUND_DOWN)
        if swap < MIN_SWAP_USD:
            return False, f'This amount is too small to cover the {chain} network fee', ''

        # 3. Front what is missing.
        sid = None
        if grant_wei:
            try:
                sid = _send_and_record(d, user_id, wallet, chain, owner_cs, grant_wei, grant_usd, PURPOSE_BUY)
            except SponsorError as e:
                return False, str(e)[:1].upper() + str(e)[1:], ''
            except Exception as e:
                return False, f'Could not set up the network fee: {d._redact_keys(str(e))[:120]}', ''

        # 4. Pay it back before the swap, together with anything still owed.
        ids = [i for i, _a in debts] + ([sid] if sid else [])
        if repay > 0:
            try:
                _repay(d, private_key, chain, ids, repay)
            except Exception as e:
                print(f'[sponsored-gas] {chain} repayment failed for {wallet[:8]}...: '
                      f'{type(e).__name__}: {d._redact_keys(str(e))[:120]}', flush=True)
                return False, 'Could not settle the network fee — nothing was bought. Please try again.', ''

        # 5. The swap, for what is left of the amount the user entered.
        return raw_execute(wallet, private_key, 'buy', token_address, str(swap), chain)


def sponsored_sell(d, raw_execute, wallet, private_key, token_address, amount_str, chain) -> tuple:
    user_id = _user_id(d, wallet)
    if not user_id:
        return False, 'User not found', ''
    w3 = d._get_web3(chain)
    owner_cs = w3.to_checksum_address(Account.from_key(private_key).address)
    stable = d.EVM_CHAINS[chain]['usdc']

    with _lock_for(owner_cs, chain):
        token_cs = w3.to_checksum_address(token_address)
        token = w3.eth.contract(address=token_cs, abi=d._ERC20_FULL_ABI)
        try:
            dec = int(token.functions.decimals().call())
            raw = int(Decimal(str(amount_str)) * (Decimal(10) ** dec))
            quote = d._get_0x_quote(token_cs, stable, raw, owner_cs, chain, apply_platform_fee=True)
        except Exception as e:
            return False, f'Could not price this sale: {d._redact_keys(str(e))[:160]}', ''
        issues = quote.get('issues') or {}
        if issues.get('balance'):
            return False, 'Insufficient token balance', ''
        txn = quote.get('transaction') or {}
        if not txn and not issues.get('allowance'):
            return False, 'No liquidity route found for this sale', ''
        units = int(txn.get('gas') or 0) or DEFAULT_SWAP_GAS
        if issues.get('allowance'):
            units += _estimate(token.functions.approve(
                w3.to_checksum_address(issues['allowance'].get('spender') or owner_cs), raw),
                owner_cs, DEFAULT_TOKEN_TX_GAS)
        erc20 = w3.eth.contract(address=w3.to_checksum_address(stable), abi=d._ERC20_FULL_ABI)
        units += _estimate(erc20.functions.transfer(
            w3.to_checksum_address(sponsor_address(d)), 1), owner_cs, DEFAULT_TOKEN_TX_GAS)
        try:
            _front(d, user_id, wallet, chain, owner_cs, units, PURPOSE_SELL)
        except SponsorError as e:
            return False, str(e)[:1].upper() + str(e)[1:], ''
        except Exception as e:
            return False, f'Could not set up the network fee: {d._redact_keys(str(e))[:120]}', ''

        result = raw_execute(wallet, private_key, 'sell', token_address, amount_str, chain)
        # Paid back out of the proceeds. If that cannot happen now it stays
        # owed and is settled before this wallet is fronted anything again.
        debts = owed(d, user_id, chain)
        if debts:
            try:
                _repay(d, private_key, chain, [i for i, _a in debts],
                       _cents_up(sum((a for _i, a in debts), Decimal(0))))
            except Exception as e:
                print(f'[sponsored-gas] {chain} repayment after sell left owed for {wallet[:8]}...: '
                      f'{type(e).__name__}', flush=True)
        return result


# ── install ─────────────────────────────────────────────────────────────────

def install(d):
    """Wrap d._execute_evm_swap (already the 0x Gasless adapter)."""
    if getattr(d, '_sponsored_gas_installed', False):
        return
    d._sponsored_gas_installed = True
    gasless_execute = d._execute_evm_swap
    raw_execute = getattr(d, '_execute_evm_swap_signed', None)
    if raw_execute is None:
        return
    # Set by the trade engine's executor to the gas it already reserved out
    # of the user's ceiling (see dashboard._te_evm_swap_executor).
    reserve = getattr(d, '_EVM_GAS_RESERVE', None) or threading.local()
    d._EVM_GAS_RESERVE = reserve

    def execute(wallet, private_key, action, token_address, amount_str, chain='bsc'):
        ok, msg, tx_hash = gasless_execute(wallet, private_key, action, token_address, amount_str, chain)
        if ok or tx_hash or not enabled(d) or chain not in getattr(d, 'EVM_CHAINS', {}):
            return ok, msg, tx_hash
        low = str(msg or '').lower()
        action = str(action).lower()
        try:
            if action == 'buy' and any(m in low for m in _NOT_SUBMITTED):
                print(f'[sponsored-gas] {chain} gasless buy not possible ({str(msg)[:120]}) '
                      f'-- fronting gas, repaid from this trade', flush=True)
                return sponsored_buy(d, raw_execute, wallet, private_key, token_address, amount_str,
                                     chain, Decimal(str(getattr(reserve, 'usd', 0) or 0)))
            if action == 'sell' and any(m in low for m in _SELL_NEEDS_GAS):
                print(f'[sponsored-gas] {chain} sell needs gas ({str(msg)[:120]}) '
                      f'-- fronting gas, repaid from the proceeds', flush=True)
                return sponsored_sell(d, raw_execute, wallet, private_key, token_address, amount_str, chain)
        except Exception as e:
            print(f'[sponsored-gas] {chain} {action} error: {type(e).__name__}: '
                  f'{d._redact_keys(str(e))[:160]}', flush=True)
            return False, f'{type(e).__name__}: {d._redact_keys(str(e))[:120]}', ''
        return ok, msg, tx_hash

    d._execute_evm_swap = execute
