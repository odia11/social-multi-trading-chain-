"""The two files that have to agree on whether money left the wallet.

orcagent_solana.py prints a verdict around sendTransaction; dashboard.py's
_capture_broadcast_evidence reads it and the trade engine decides from that
whether to give a user's reserved balance back. They are separate files and
the link between them is a string, so it is the kind of thing that gets
"tidied up" in one place and silently stops working.

Silently is the problem. If the markers stop matching, nothing raises -- the
executor just falls back to reading step numbers, and a swap the node refused
starts being treated as possibly-sent again, freezing the user's own money
until the reaper releases it 15 minutes later. That is why this is pinned.
"""
import os
import re
import sys
import tempfile

os.environ.setdefault('DATA_DIR', tempfile.mkdtemp())
os.environ.setdefault('SECRET_KEY', 'x' * 32)
os.environ.setdefault('ENCRYPTION_KEY', 'K' * 43 + '=')
os.environ.setdefault('DEV', '1')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

SOL = open(os.path.join(ROOT, 'orcagent_solana.py')).read()
DASH = open(os.path.join(ROOT, 'dashboard.py')).read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


# ── the swap emits every verdict ──────────────────────────────────────────
check('the swap announces that a send is starting',
      "print('[BROADCAST] begin'" in SOL)
check('...and prints the signature when one comes back',
      "[BROADCAST] sent {sig}" in SOL)
check('...and says outright when the node refused it',
      "'[BROADCAST] ' + ('rejected ' if _send_clean else 'unknown ')" in SOL)
check('...and says unknown when every endpoint died mid-request, rather than '
      'reporting a clean failure it cannot actually vouch for',
      '[BROADCAST] unknown all sendTransaction endpoints failed' in SOL)

# ── the reader looks for exactly those strings ────────────────────────────
for const, literal in (('_BC_BEGIN', '[BROADCAST] begin'),
                       ('_BC_SENT', '[BROADCAST] sent'),
                       ('_BC_REJECTED', '[BROADCAST] rejected'),
                       ('_BC_UNKNOWN', '[BROADCAST] unknown')):
    m = re.search(re.escape(const) + r"\s*=\s*'([^']*)'", DASH)
    check(f'{const} is the literal the swap actually prints',
          bool(m) and m.group(1) == literal)


# ── "rejected" is only claimed when it is true ────────────────────────────
# A rejection releases the user's entire claim, so it may only be printed
# when every endpoint that was reached answered in full. If one died
# mid-request it may have broadcast the transaction before the reply was
# lost, and the verdict has to soften to unknown.
check('a rejection is conditional on no endpoint having died mid-request — '
      'otherwise the node may have broadcast it and the reply was simply lost',
      '_send_clean = (_LAST_RPC_TRANSPORT_ERRORS == 0)' in SOL)
check('...and _rpc_post counts those transport failures, rather than the '
      'send path assuming there were none',
      '_LAST_RPC_TRANSPORT_ERRORS += 1' in SOL
      and '_LAST_RPC_TRANSPORT_ERRORS = 0' in SOL)
check('the counter is reset at the START of each call, so one call cannot '
      'inherit the previous call\'s failures',
      re.search(r"global _LAST_RPC_TRANSPORT_ERRORS\s*\n\s*_LAST_RPC_TRANSPORT_ERRORS = 0",
                SOL) is not None)

# ── preflight is what makes a rejection mean "not broadcast" ──────────────
check('preflight stays ON for the send — with skipPreflight the node would '
      'forward a transaction it had not simulated, and a later error would '
      'no longer prove nothing was broadcast',
      "'skipPreflight': False" in SOL)

# ── the engine still refuses to be optimistic without evidence ────────────
import dashboard as d                                              # noqa: E402

cap = {}
d._capture_broadcast_evidence(cap, '')
check('a subprocess that produced no output at all never reached the send, '
      'so the claim goes back', cap['send_attempted'] is False)
cap = {}
d._capture_broadcast_evidence(cap, 'random unrelated output\n')
check('...and output with no markers falls back to the step heuristic rather '
      'than to a guess', cap['send_attempted'] is False)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
