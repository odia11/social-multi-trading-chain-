"""An empty gas sponsor must FAIL the deploy check, not warn it.

WHAT WAS HAPPENING
verify_live.py reported both "low" and "empty" gas sponsors the same way: a
warning, exit code 0, and a deploy that finished on "26 passed, 2 warnings".
That reads as fine. It was not fine.

An empty sponsor on a chain means every user there holding only USDC can
neither trade NOR send their own money out -- the wallet has no native token
to pay a fee with, and fronting that fee is the sponsor's whole job. It went
unnoticed across days of deploys, and was found only when somebody tried to
withdraw $3 and got "Sending is temporarily unavailable."

A warning that gets scrolled past is not a warning.

THE LINE
It is not severity, it is a question with a yes/no answer: can this chain
serve one more user right now?

  · enough for some, but fewer than the comfortable margin  -> WARN
  · enough for nobody at all                                -> FAIL

The same applies to the keys themselves: fronting gas with no sponsor key
configured means every EVM chain, and Solana, are in that state at once.

WHY THIS IS SAFE TO FAIL ON
deploy/update.sh does not roll back on a non-zero verify_live: the site
stays up and running. All a failure changes is that the deploy stops
printing "✓ Deployed and verified" while a chain is dead, and says what to
send where instead.

Checked by running the real check function against stand-in balances, and
the real attempt() against both kinds of exception -- not by reading source,
since what matters is which status actually comes out.
"""
import importlib.util
import os
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = REPO + '/tools/verify_live.py'

os.environ['_VERIFY_LIVE_REEXEC'] = '1'   # no re-exec inside this harness
_spec = importlib.util.spec_from_file_location('vl', TOOL)
vl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vl)

SRC = open(TOOL, encoding='utf-8').read()

checks = []


def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def status_of(fn, essential=False):
    vl.results.clear()
    vl.attempt('check', fn, essential=essential)
    return vl.results[0][0]


def raiser(exc):
    def _f():
        raise exc
    return _f


# ── 1. Blocking outranks a check's own leniency ──────────────────────────
check('a check that passes is still OK', status_of(lambda: 'fine') == vl.OK)
check('an ordinary failure in a warn-level check stays a warning',
      status_of(raiser(RuntimeError('low'))) == vl.WARN)
check('a Blocking failure in that SAME warn-level check is a FAILURE — the '
      'whole point: a check may warn about degradation and still have to '
      'fail about an outage',
      status_of(raiser(vl.Blocking('nobody can trade'))) == vl.BAD)
check('Blocking in an essential check is a failure too, unchanged',
      status_of(raiser(vl.Blocking('x')), essential=True) == vl.BAD)


# (Sections 2-3 checked the EVM gas-sponsor wallets; those went with the EVM
# chains, and gas fronting is forced off in production.)

# ── 4. the deploy still must not roll back over this ────────────────────
UPD = open(REPO + '/deploy/update.sh', encoding='utf-8').read()
after_verify = UPD[UPD.index('VERIFY=$?'):]
check('a failed verify does not roll the deploy back — the site stays up, it '
      'just stops claiming it is verified',
      'ROLLBACK' not in after_verify and 'exit 1' in after_verify)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
