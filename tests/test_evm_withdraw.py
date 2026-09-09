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
      'failed transaction', 'Cannot send from' in w)

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

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
