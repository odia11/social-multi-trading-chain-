"""Getting money OUT of an EVM chain.

WHAT WAS MISSING
/api/withdraw is Solana-only: it validates a base58 address and signs with a
Solana keypair, so an 0x destination was rejected outright. The bridge is no
substitute — it takes an origin chain and a destination chain, never a
recipient, so it can only move funds between a user's own chains. There was
simply no way to send USDC from an EVM chain to an address you name.

WHAT THIS PATH HAS TO GET RIGHT
It moves real money out, on a request anyone can craft, so nothing the page
sends may be trusted: the amount is checked against the balance the SERVER
reads and the destination is validated server-side even though the form
validates it too.

And a withdrawal that runs twice has sent the money twice. Two requests
arriving together would each read the same balance, each pass, and each
broadcast — so they are serialised. A repeat arriving after the first has
finished is a different problem with the same cost, so an identical
withdrawal inside a short window is refused as the double-tap it almost
always is.
"""
import ast
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/dashboard.py').read()
TREE = ast.parse(SRC)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def fn(name):
    f = next(n for n in ast.walk(TREE)
             if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SRC, f) or ''


check('there is an EVM withdrawal route at all', "@app.route('/api/withdraw/evm'" in SRC)
w = fn('api_withdraw_evm')

# ── nothing the page says is taken on trust ───────────────────────────────
check('it requires an authenticated wallet before anything else',
      '_authenticated_wallet()' in w
      and w.index('_authenticated_wallet()') < w.index('to_address'))
check('the destination is validated on the SERVER, since this endpoint is '
      'reachable without the form', 'is_valid_evm_address(to_address)' in w)
check('the chain must be one this app actually knows', "chain not in EVM_CHAINS" in w)
check('a non-numeric amount is refused rather than coerced',
      'except (TypeError, ValueError)' in w)
check('the amount is checked against the balance THIS SERVER reads, never one '
      'the page sent', 'get_evm_usdc_balance(evm_address, chain)' in w
      and 'if amount > balance' in w)
check('...and an unreadable balance refuses the withdrawal instead of '
      'assuming it is fine', "Could not read your" in w)
check('sending to the wallet the money is already in is caught as the mistake '
      'it is, not paid for', "to_address.lower() == evm_address.lower()" in w)

# ── a withdrawal must never run twice ─────────────────────────────────────
check('concurrent requests are serialised, or two would each read the same '
      'balance, each pass, and each send',
      '_get_evm_withdraw_lock(wallet, chain)' in w and 'acquire(blocking=False)' in w)
check('...and the second is refused rather than queued behind the first, '
      'because by the time it ran the balance it was checked against is gone',
      "already in progress" in w and '409' in w)
check('...and the lock is always released, including on any error path',
      'finally:' in w and 'lock.release()' in w)
check('a repeat that arrives AFTER the first finished is refused too — the '
      'lock cannot see that one', '_recent_evm_withdrawals' in w)
check('...keyed on the whole withdrawal, so a genuinely different amount or '
      'destination is never blocked',
      "(wallet, chain, to_address.lower(), round(amount, 6))" in w)
check('...and recorded only once the transfer is really on-chain, so a failed '
      'attempt does not lock out the retry it needs',
      w.index('tx_hash = _send_evm_usdc_fee') < w.index('_recent_evm_withdrawals[_key] = time.time()'))

lock = fn('_get_evm_withdraw_lock')
check('the lock registry is itself guarded, or two callers could create two '
      'different locks for the same wallet', '_evm_withdraw_locks_guard' in lock)

# ── the money can only move if gas exists ─────────────────────────────────
check('gas is arranged before the transfer, since an ERC20 send is paid in the '
      'chain\'s NATIVE token and a USDC-only wallet cannot move its own USDC',
      '_ensure_evm_gas(' in w and w.index('_ensure_evm_gas(') < w.index('_send_evm_usdc_fee'))
check('...and a wallet that cannot get gas is told so rather than left with a '
      'failed transaction — through the translator, so it never shows our own '
      'reason for it (see tests/test_gas_message_privacy.py)',
      "_gas_refusal_message(" in w and "'send'" in w)

# ── the amount is a ceiling, and the fee comes out of it ──────────────────
# Same shape as a trade: the number typed is the MOST that leaves the wallet.
# Arranging gas can spend some of that very USDC to buy the native token, so
# the figure checked a moment earlier is stale by exactly the amount this is
# meant to account for.
check('the balance is read again AFTER gas is arranged, because arranging it '
      'may have just spent some of the USDC being sent',
      w.index('_ensure_evm_gas(') < w.index('spendable = get_evm_usdc_balance')
      and w.index('spendable = get_evm_usdc_balance') < w.index('_send_evm_usdc_fee'))
check('...and the transfer is capped at what survived, so the fee comes out of '
      'the amount rather than on top of it', 'send_amount = min(amount, spendable)' in w)
check('...floored, never rounded — rounding up asks for a fraction more than '
      'the wallet holds and reverts on-chain, having spent the gas anyway',
      'math.floor(send_amount' in w)
check('a fee that eats the whole amount is refused with a reason, not sent as '
      'a zero transfer', 'send_amount <= 0' in w and 'used up the whole amount' in w)
check('a failure to re-read the balance refuses rather than falling back to '
      'the stale one', 'after arranging gas' in w)

# Sending less than was asked for is fine. Doing it quietly is not.
check('the response reports what actually left, not what was asked for',
      "'amount_sent': send_amount" in w)
check('...alongside the request and the difference, so the confirmation can be '
      'reconciled against the explorer',
      "'amount_requested': amount" in w and "'fee_deducted'" in w)
check('...and the transfer itself uses the capped figure, not the requested one',
      '_send_evm_usdc_fee(_pk, to_address, send_amount, chain)' in w)
check('the activity log records the amount that left, and names the shortfall '
      'when there was one',
      'went to network fees' in w and '{send_amount} {sym}' in w)
check('the repeat-guard still keys on what the USER asked for, or an identical '
      'resubmission would look different every time the fee moved',
      "round(amount, 6))" in w)

# ── it costs the same budget as the Solana one ────────────────────────────
check('it shares the Solana withdrawal budget of 3 per hour, so the limit is '
      'per user and not per chain — the point is how much leaves, not how',
      "_rate_ok('withdraw_wallet:' + wallet, 3, 3600)" in w)
sol = fn('api_withdraw')
check('...the very same key the Solana route uses',
      "_rate_ok('withdraw_wallet:' + wallet, 3, 3600)" in sol)

# ── it says what happened ─────────────────────────────────────────────────
check('the user gets it in their own activity log, with the transaction',
      'add_user_log(' in w and 'WITHDRAW:' in w)
check('...and the response carries an explorer link, so it can be checked '
      'rather than believed', "'explorer':" in w)
check('a key never reaches a log line or an error message', '_redact_keys(' in w)

# ── the page offers it ────────────────────────────────────────────────────
WAL = open(REPO + '/templates/wallet.html').read()
check('Send is a chain choice now, instead of silently meaning SOL',
      '_SEND_CHAINS' in WAL and "id=\"send-chain\"" in WAL)
check('...with each option naming the token it actually moves, so nobody has '
      'to guess what Send does on a given chain',
      "'Base (USDC)'" in WAL and "'Solana (SOL)'" in WAL)
check('...routing an EVM chain to the new endpoint and Solana to the old one',
      "c.evm ? '/api/withdraw/evm' : '/api/wallet/send'" in WAL)
check('...sending the field names each route actually reads',
      "{chain:c.v, to_address:to, amount:amt}" in WAL
      and "{to:to, amount_sol:amt}" in WAL)
check('the button is disabled while a send is in flight, so a second tap '
      'cannot start a second one', 'btn.disabled=true' in WAL)
check('the form says up front that the fee comes out of the amount, rather '
      'than leaving it to be discovered in the confirmation',
      'comes out of this amount' in WAL)
check('...and the confirmation shows what actually left plus the fee, instead '
      'of echoing the number that was typed',
      'd.amount_sent' in WAL and 'd.fee_deducted' in WAL)

# ── MAX ───────────────────────────────────────────────────────────────────
# It means two different things, because the fee is paid in two different
# places: out of the amount on an EVM chain, out of the same token on Solana.
check('there is a MAX button on the Send form', '_sendSetMax()' in WAL)
check('on an EVM chain MAX is the whole balance, because the server takes the '
      'fee out of it rather than needing headroom on top',
      'c.evm ? b : Math.max(0, b - SOL_FEE_RESERVE)' in WAL)
check('...while Solana keeps a reserve back, since the fee is paid in the very '
      'token being sent and /api/wallet/send deducts nothing',
      'SOL_FEE_RESERVE' in WAL and 'left behind to pay the network fee' in WAL)
check('...and says so, rather than silently filling in less than the balance',
      "note.textContent = c.evm ? ''" in WAL)
check('MAX is floored to 6 decimals for the same reason the server floors it — '
      'a value rounded up is a fraction more than the wallet holds',
      'Math.floor(max * 1e6) / 1e6' in WAL)
check('a balance that is not loaded yet is fetched rather than filled in as a '
      'zero that looks like an answer',
      'Fetching your balance' in WAL and 'b===null' in WAL)
check('...and it gives up with a message instead of retrying forever',
      'Could not read your balance' in WAL)
check('the balance line reads "—" when unknown, since an empty line says "you '
      'have nothing" and that is a different statement',
      "'Balance: —'" in WAL)
check('the SOL balance is remembered when the page loads it, so the form has '
      'a figure without fetching its own', '_solBalanceCache=parseFloat(d.sol)' in WAL)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
