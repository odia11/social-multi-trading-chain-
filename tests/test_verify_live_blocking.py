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

REPO = '/home/user/Orc-agent-Solana-chain-'
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


# ── 2. the sponsor check draws the line at "can it serve one more user" ──
ONE_GWEI, GAS_UNITS, MULT = 10 ** 9, 200000, 3
ONE_GRANT = ONE_GWEI * GAS_UNITS * MULT / 1e18


def fake_dashboard(balances):
    d = types.SimpleNamespace()
    d.ORCAGENT_FRONTS_GAS = True
    d.EVM_CHAINS = {'bsc': {'native_symbol': 'BNB'},
                    'robinhood': {'native_symbol': 'ETH'}}
    d._gas_sponsor_address = lambda: '0xSPONSOR'
    d.get_evm_native_balance = lambda a, c: balances[c]
    d.GAS_TOPUP_TX_GAS_UNITS = GAS_UNITS
    d.GAS_SPONSOR_TX_MULTIPLIER = MULT
    d._get_web3 = lambda c: types.SimpleNamespace(
        eth=types.SimpleNamespace(gas_price=ONE_GWEI))
    return d


def evm_sponsor_with(balances, addr='0xSPONSOR'):
    """The REAL evm_sponsor(), lifted out of main() and run against
    stand-in balances -- so this tests the shipped arithmetic, not a copy."""
    body = SRC[SRC.index('    def evm_sponsor():'):
               SRC.index("    attempt('EVM gas sponsor funding'")]
    body = ''.join(l[4:] if l.startswith('    ') else l for l in body.splitlines(True))
    d = fake_dashboard(balances)
    d._gas_sponsor_address = lambda: addr
    ns = {'d': d, 'Blocking': vl.Blocking, '_fronting': True,
          'WARN_BELOW_GRANTS': 5, 'TARGET_GRANTS': 30,
          '_grants_left': lambda b, g: int(b // g) if g > 0 else 0}
    exec(body, ns)
    vl.results.clear()
    vl.attempt('EVM gas sponsor funding', ns['evm_sponsor'], essential=False)
    return vl.results[0][0], vl.results[0][2]


st, _ = evm_sponsor_with({'bsc': ONE_GRANT * 40, 'robinhood': ONE_GRANT * 40})
check('sponsors with plenty in them pass', st == vl.OK)

st, detail = evm_sponsor_with({'bsc': ONE_GRANT * 40, 'robinhood': ONE_GRANT * 3})
check('a sponsor that is low but can still activate users only WARNS — a '
      'float to top up soon is not an outage', st == vl.WARN)
check('...and says how much to send to get back to a comfortable margin',
      'send ' in detail and 'robinhood' in detail)

st, detail = evm_sponsor_with({'bsc': ONE_GRANT * 40, 'robinhood': 0.0})
check('a sponsor that cannot activate a single user FAILS the run', st == vl.BAD)
check('...naming the chain nobody can use', 'robinhood' in detail)
check('...in words that say what it means for a person, not "low balance"',
      'NOBODY can trade or withdraw' in detail)
check('...and still says exactly what to send', 'send ' in detail and 'ETH' in detail)
check('...while a healthy chain in the same run is not dragged in with it',
      'NOBODY can trade or withdraw on: robinhood' in detail)

st, detail = evm_sponsor_with({'bsc': 0.0, 'robinhood': 0.0})
check('several blocked chains are all named, not just the first',
      st == vl.BAD and 'bsc' in detail and 'robinhood' in detail)

# ── 3. no key at all, while the deployment says it fronts gas ────────────
st, detail = evm_sponsor_with({'bsc': ONE_GRANT * 40, 'robinhood': ONE_GRANT * 40},
                               addr='')
check('fronting gas with no sponsor key configured is a FAILURE, not a note '
      '— it is every EVM chain blocked at once', st == vl.BAD)
check('...and it offers the honest alternative rather than only an error',
      'ORCAGENT_FRONTS_GAS=0' in detail)

# ── 4. the deploy still must not roll back over this ────────────────────
UPD = open(REPO + '/deploy/update.sh', encoding='utf-8').read()
after_verify = UPD[UPD.index('VERIFY=$?'):]
check('a failed verify does not roll the deploy back — the site stays up, it '
      'just stops claiming it is verified',
      'ROLLBACK' not in after_verify and 'exit 1' in after_verify)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
