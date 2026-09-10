"""What a person is told when a chain cannot be used.

WHAT THEY WERE TOLD
    cannot trade on robinhood yet — we are topping up the network fees for
    this chain. Nothing to do on your side — try again shortly.

Three things wrong with that, on the one screen where somebody is trying to
spend money with us. It describes our own plumbing. It names a chain in a raw
lowercase slug. And it hands over a fact the reader can do nothing with --
"nothing to do on your side" is the sentence admitting that.

WHAT REPLACES IT
"Trading is temporarily unavailable. Please try again shortly." Nothing about
sponsors, float or network fees. Not silence either: a Confirm button that
does nothing at all is worse than any message, so something still appears.

WHAT IS NOT TOUCHED
The other branch, where the person's OWN wallet is genuinely short of gas.
That message is a real instruction they can act on -- send a little ETH here
-- so it survives intact, chain named, because they need to know which one.

The distinction is kept by returning a sentinel rather than a sentence, so a
caller cannot accidentally print the internal reason: there is no internal
reason to print.
"""
import ast
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/dashboard.py', encoding='utf-8').read()
TREE = ast.parse(SRC)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

def fn(name):
    f = next(n for n in ast.walk(TREE)
             if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SRC, f) or ''

# ── 1. the text itself is gone ────────────────────────────────────────────
check('the message describing our own plumbing is gone, not reworded',
      'topping up the network fees' not in SRC
      and 'Nothing to do on your side' not in SRC)

# ── 2. and what it became ─────────────────────────────────────────────────
# Checked by CALLING it, not by reading its source. An earlier version of
# this file matched text between the first two `return`s, and when a second
# branch was added it went on passing while silently covering only half of
# what it claimed.
import os
import tempfile
os.environ.setdefault('DATA_DIR', tempfile.mkdtemp())
os.environ.setdefault('SECRET_KEY', 'x' * 32)
os.environ.setdefault('ENCRYPTION_KEY', 'K' * 43 + '=')
os.environ.setdefault('DEV', '1')
sys.path.insert(0, REPO)
import dashboard as d  # noqa: E402

translate = fn('_gas_refusal_message')


def say(action='send', chain='Robinhood Chain', self_heals=True):
    """The sentence a user gets for an outage that is OURS, with the sponsor
    either able to refill itself or not configured at all."""
    _keep_key, _keep_rule = d.GAS_SPONSOR_PRIVATE_KEY, d.ORCAGENT_FRONTS_GAS
    try:
        d.ORCAGENT_FRONTS_GAS = True
        d.GAS_SPONSOR_PRIVATE_KEY = ('0x' + '11' * 32) if self_heals else ''
        return d._gas_refusal_message(d.GAS_UNAVAILABLE, action, chain)
    finally:
        d.GAS_SPONSOR_PRIVATE_KEY, d.ORCAGENT_FRONTS_GAS = _keep_key, _keep_rule


healing = say(self_heals=True)
stuck = say(self_heals=False)

check('a refusal that is OUR fault, while the sponsor can still refill '
      'itself, becomes a plain "temporarily unavailable"',
      'temporarily unavailable' in healing)
check('...phrased as whatever the person was actually doing, so a Sell does '
      'not say "Trading"',
      say('sell', self_heals=True).startswith('Selling')
      and say('send', self_heals=True).startswith('Sending'))
check('...naming no chain, since there is nothing about the chain they could '
      'act on',
      'Robinhood' not in healing)

# The outage that will NOT clear on its own. "Try again shortly" there is a
# promise nothing keeps: the person taps Send at their own money forever.
check('an outage that cannot fix itself does NOT tell the user to wait',
      'try again' not in stuck.lower() and 'shortly' not in stuck.lower())
check('...it points them somewhere that can actually help, and says plainly '
      'that retrying is not it',
      'support' in stuck.lower() and 'not clear this' in stuck.lower())
check('...and names the chain, so they can see it is that one chain rather '
      'than their whole wallet',
      'Robinhood Chain' in stuck)
check('...while still describing none of our plumbing',
      not any(w in stuck.lower() for w in
              ('sponsor', 'float', 'network fee', 'gas', 'top up', 'top-up')))

check('the other branch survives intact — a wallet genuinely short of gas '
      'gets a real instruction, with the chain named, because they need to '
      'know which one',
      'chain_label' in translate.rsplit('return', 1)[1])
own = d._gas_refusal_message('send a little ETH to it', 'send', 'Base')
check('...and that instruction reaches the user unchanged',
      'send a little ETH to it' in own and 'Base' in own)

# ── 3. it cannot leak by accident ─────────────────────────────────────────
# A sentinel rather than a sentence: a caller that forgets to translate shows
# something obviously wrong in testing, instead of quietly shipping the
# internal explanation to users.
check('the internal case is carried as a sentinel, not as text a caller could '
      'print by mistake',
      re.search(r"GAS_UNAVAILABLE\s*=\s*'__[a-z_]+__'", SRC))

# Every place a gas message reaches a person has to go through the translator.
# Found by reading the code rather than by listing them here, so a new caller
# added later is checked too.
leaks = []
for n in ast.walk(TREE):
    if not isinstance(n, ast.FunctionDef):
        continue
    body = ast.get_source_segment(SRC, n) or ''
    if '_ensure_evm_gas(' not in body or n.name == '_ensure_evm_gas':
        continue
    for lineno, line in enumerate(body.split('\n'), 1):
        # a gas message being put in front of a person: interpolated into a
        # message, a log, an error, or returned as one
        if re.search(r'\{_?gas_msg\}', line) or re.search(r'=\s*False,\s*_?gas_msg\b', line):
            leaks.append(f'{n.name}:{lineno}: {line.strip()[:80]}')
for l in leaks:
    print('   leaks: ' + l)
check('every place a gas refusal reaches a person goes through the translator '
      '— none of them interpolates the raw message, which is how the sentinel '
      'would end up on screen', not leaks)

# ── 4. the operator still gets the whole story ────────────────────────────
# Read the function that actually holds it, rather than slicing a guessed
# number of characters out of the file — the first shape of this check sliced
# a window that did not contain the log at all and then crashed on it.
bootstrap = fn('_bootstrap_evm_gas_via_bridge')
check('the detail is not lost, only moved: the operator log still says which '
      'chain is blocked and that every USDC-only user is stuck on it until it '
      'is funded',
      'CANNOT ACTIVATE' in bootstrap and 'Top up the sponsor' in bootstrap)
_after = bootstrap.split('CANNOT ACTIVATE')[1][:500]
check('...as a server log, not in the user\'s own journal — the operator is '
      'the only person who can act on it', 'add_user_log' not in _after)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
