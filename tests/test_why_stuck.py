"""A script that answers "why can this wallet not send" in one run.

WHY IT EXISTS
Four different conditions produce the same refusal on screen: the user's
wallet is out of gas, the sponsor wallet is empty, an RPC is down, or
fronting is off. The journal only records the attempt that happened to be
made, so telling them apart was costing a round trip per guess — and this
session spent several of them doing exactly that.

WHAT IT MUST NOT DO
Read-only, like verify_live.py. It answers a question about money; it never
moves any, and it never prints a key.
"""
import ast
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/tools/why_stuck.py').read()

# A sentence a user reads must not depend on where the source happens to
# wrap, and asserting on the raw text makes it depend on exactly that -- this
# suite has now been caught out by it three times. Matching happens against a
# copy with the f-string continuations joined; SRC itself stays available for
# the checks that really are about the code.
def _joined(text):
    return re.sub(r"'\s*\n\s*f?'", '', text)
JOINED = None   # set after re is imported below
DASH = open(REPO + '/dashboard.py').read()
TREE = ast.parse(SRC)
JOINED = _joined(SRC)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


# ── it must not be able to move money ─────────────────────────────────────
for forbidden, why in [
    ('_use_key', 'it never decrypts a trading key'),
    ('send_raw_transaction', 'it never broadcasts'),
    ('sign_transaction', 'it never signs'),
    ('_send_evm_usdc_fee', 'it never transfers'),
    ('_sponsor_evm_gas', 'it never hands out a grant'),
]:
    check(f'{why} — no {forbidden}', forbidden not in SRC)
check('...and it says so where someone will read it, not only in a review',
      'Read-only' in SRC and 'Signs nothing, sends nothing' in SRC)
check('...including on the way out of an unexpected error, where a reader is '
      'most likely to wonder', 'only reads. Nothing was signed or sent' in SRC)
check('no key is ever printed', 'PRIVATE_KEY' not in SRC.replace(
      "GAS_SPONSOR_PRIVATE_KEY is not set", ''))

# ── every name it reaches for on the app has to exist ─────────────────────
_names = set()
for n in ast.walk(ast.parse(DASH)):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        _names.add(n.name)
    elif isinstance(n, ast.Assign):
        for t in n.targets:
            if isinstance(t, ast.Name):
                _names.add(t.id)
_used = set(re.findall(r'\bd\.([A-Za-z_][A-Za-z0-9_]*)', SRC))
_missing = sorted(_used - _names)
check('every attribute it reads off the app actually exists — a typo here '
      f'costs a trip to the server to discover{"" if not _missing else ": " + ", ".join(_missing)}',
      not _missing)

# ── it has to separate the four causes ────────────────────────────────────
check('an unreachable RPC is named as such, not reported as an empty wallet',
      'RPC unreachable' in SRC and "'RPC down'" in SRC)
check('a wallet that simply has enough gas is cleared, so the chain can be '
      'ruled out', 'this chain is not the problem' in JOINED)
check('a wallet holding both a little gas and some stablecoin is identified as '
      'able to fund itself, which needs no intervention at all',
      'can buy its own gas' in JOINED)
check('an empty SPONSOR is called out as the blocker, in those words, because '
      'that is the case that looks like the user\'s fault and is not',
      'THIS is the blocker' in JOINED and 'sponsor empty' in SRC)
check('the anti-farming gate is distinguished from a fault — a withheld grant '
      'there is policy working, not something broken',
      'anti-farming' in JOINED and 'withheld by design' in JOINED
      and 'Deposit something to trade with first' in JOINED)
check('fronting being off is its own answer, since then a manual top-up is the '
      'correct instruction rather than a workaround',
      'fronting is off' in JOINED and 'needs a manual top-up' in SRC)

# ── it has to say what to do, with numbers ────────────────────────────────
check('an empty sponsor gets an amount to send, not just a diagnosis',
      'GAS_SPONSOR_TARGET_GRANTS' in SRC and 'Send {' in SRC.replace("\n", ""))
check('...and the cheaper alternative that unblocks only this wallet, since '
      'that is often what someone actually wants right now',
      'to unblock just this wallet' in JOINED)
check('balances are reported as how many users they could still activate, the '
      'same unit verify_live.py uses', 'users)' in SRC)
check('it ends with a one-line verdict per chain, so the answer does not have '
      'to be reconstructed from the detail above it', 'verdicts.append(' in SRC)

# ── it has to be usable by the person who needs it ────────────────────────
check('the wallet defaults to OWNER_WALLET, so the common case needs no '
      'arguments', "os.getenv('OWNER_WALLET'" in SRC)
check('...and a single chain can be named when only one is in question',
      'sys.argv[2]' in SRC)
check('a user with no EVM trading key is told that plainly, rather than being '
      'shown five chains of irrelevant balances',
      'no EVM trading key' in SRC)
check('an unexpected error prints its traceback instead of a bare exit, since '
      'this is the tool someone runs when they are already stuck',
      'traceback.print_exc()' in SRC)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
