"""Which chain's money funds a trade, and whether the user can pay for the gas.

TWO QUESTIONS THE USER SHOULD NEVER HAVE TO ANSWER
"Where are my dollars?" and "do I have enough of this chain's token to sign a
transaction?" The first is routing and the app answers it. The second is gas,
and the app can only answer it honestly -- there is no arrangement under
which OrcAgent pays it, so when the answer is no the user is told so before
anything is signed rather than after.

The gas checks here are the ones that matter most, because the tempting bug
is not a crash. It is a route that looks like it worked, quietly funded from
a platform wallet, which is a cost that never stops.
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


PROBE = r'''
import json, sys
import dashboard as d

out = {}
WALLET = 'W_ROUTE'

# Balances per chain, and native balances per chain, both stubbed at the
# point the app reads them.
USDC = {'solana': 0.0, 'base': 0.0, 'bsc': 0.0, 'arbitrum': 0.0,
        'polygon': 0.0, 'robinhood': 0.0}
NATIVE = {'solana': 0.0, 'base': 0.0, 'bsc': 0.0, 'arbitrum': 0.0,
          'polygon': 0.0, 'robinhood': 0.0}
d._cc_taker_address = lambda w, c: ('SoLwallet1111111111111111111111111111111111'
                                    if c == 'solana' else
                                    '0x1111111111111111111111111111111111111111')
d._cc_usdc_balance = lambda w, c: USDC.get(c, 0.0)
d._cc_native_balance = lambda w, c: NATIVE.get(c, 0.0)

def route(dest, amount):
    return d._cc_pick_source_chain(WALLET, dest, amount)

# ── everything off ──
out['flag_default'] = bool(d.TRADE_ENGINE_CROSSCHAIN)
out['routes_default'] = sorted(d.CROSSCHAIN_ENABLED_ROUTES)
USDC['base'] = 200.0
out['off_route'] = route('solana', 50.0)

# ── feature on, routes named ──
d.TRADE_ENGINE_CROSSCHAIN = True
d.CROSSCHAIN_ENABLED_ROUTES = frozenset({'base->solana', 'solana->base'})

# A: destination already funded -> no bridge
USDC.update({'solana': 100.0, 'base': 200.0})
out['A'] = route('solana', 50.0)

# B: destination empty, source funded -> bridge
USDC.update({'solana': 0.0, 'base': 200.0})
out['B'] = route('solana', 50.0)

# C: destination has exactly enough -> still no bridge
USDC.update({'solana': 50.0, 'base': 200.0})
out['C'] = route('solana', 50.0)

# D: destination has SOME but not enough, source has plenty
#    -> one source, not a split
USDC.update({'solana': 20.0, 'base': 200.0})
out['D'] = route('solana', 50.0)

# E: nobody has enough on their own
USDC.update({'solana': 20.0, 'base': 20.0})
out['E'] = route('solana', 50.0)

# F: a route that is not enabled is not used, even with the money on it
USDC.update({'solana': 0.0, 'base': 0.0, 'polygon': 500.0})
out['F'] = route('solana', 50.0)

# ── gas ──
d.TRADE_ENGINE_CROSSCHAIN = True
NATIVE.update({'base': 0.0, 'solana': 0.0, 'bsc': 0.0})
out['gas_base_empty'] = d._cc_gas_requirement(WALLET, 'base')
out['gas_solana_empty'] = d._cc_gas_requirement(WALLET, 'solana')
out['gas_bsc_empty'] = d._cc_gas_requirement(WALLET, 'bsc')
NATIVE.update({'base': 0.01, 'solana': 0.05, 'bsc': 0.01})
out['gas_base_funded'] = d._cc_gas_requirement(WALLET, 'base')
out['gas_solana_funded'] = d._cc_gas_requirement(WALLET, 'solana')

# ── the no-subsidy invariant, read off the code itself ──
import inspect
out['gas_src'] = inspect.getsource(d._cc_gas_requirement)
out['sender_src'] = inspect.getsource(d._te_cc_source_sender)
out['fronts_gas_direct'] = d.ORCAGENT_FRONTS_GAS

# ── robinhood ──
out['hood_stable'] = d.te_registry.CHAINS['robinhood'].stable.symbol
out['hood_decimals'] = d.te_registry.CHAINS['robinhood'].stable.decimals
out['hood_enabled'] = d._cc_route_enabled('robinhood', 'base') or \
                      d._cc_route_enabled('base', 'robinhood')

# ── solana platform fee stays zero ──
out['solana_fee_rate'] = str(d._te_fee_rate_for('solana'))

print('@@@' + json.dumps(out, default=str))
'''

env = dict(os.environ)
env.update({'DATA_DIR': tempfile.mkdtemp(), 'SECRET_KEY': 'x' * 32,
            'ENCRYPTION_KEY': 'K' * 43 + '=', 'DEV': '1'})
p = subprocess.run([sys.executable, '-c', PROBE], cwd=REPO, env=env,
                   capture_output=True, text=True, timeout=300)
if '@@@' not in p.stdout:
    print(p.stdout[-3000:]); print(p.stderr[-3000:])
    sys.exit('probe did not report')
R = json.loads(p.stdout.split('@@@', 1)[1].splitlines()[0])


# ── the flags ────────────────────────────────────────────────────────────
check('cross-chain is OFF by default — no route on it has been watched '
      'completing against the live API, and a flag that defaults on would '
      'make the first real trade the test', R['flag_default'] is False)
check('...and no route is enabled by default either, so turning the feature '
      'on still enables nothing: each direction has to be named',
      R['routes_default'] == [])
check('with the feature off, a trade never routes across chains however the '
      'balances fall', R['off_route']['bridge_required'] is False)


# ── routing ──────────────────────────────────────────────────────────────
check('A. the destination chain already holds enough -> no bridge. A bridge '
      'that does not happen costs nothing, takes no time, and cannot get '
      'stuck halfway', R['A']['bridge_required'] is False
      and R['A']['source_chain'] == 'solana')
check('B. the destination is empty and another chain is funded -> bridge from '
      'the funded one', R['B']['bridge_required'] is True
      and R['B']['source_chain'] == 'base')
check('C. exactly enough on the destination still means no bridge — "enough" '
      'is enough', R['C']['bridge_required'] is False)
check('D. some on the destination but not enough -> ONE source chain, not a '
      'split. Twenty from Solana plus thirty bridged is two executions and '
      'two things to recover, to bridge thirty instead of fifty',
      R['D']['bridge_required'] is True and R['D']['source_chain'] == 'base')
check('E. nobody holds enough on their own -> no route is invented, and it '
      'says so', R['E'].get('insufficient') is True)
check('F. a chain holding the money on a route nobody enabled is not used — '
      'being possible is not the same as being tested',
      R['F'].get('insufficient') is True)


# ── gas, honestly ────────────────────────────────────────────────────────
for chain, key in (('Base', 'gas_base_empty'), ('Solana', 'gas_solana_empty'),
                   ('BNB Chain', 'gas_bsc_empty')):
    g = R[key]
    check(f'{chain}: a wallet with no native token cannot bridge out, and is '
          f'told so BEFORE anything is signed', g['required'] is True
          and g['code'] == 'NATIVE_GAS_REQUIRED')
    check(f'{chain}: ...naming the token and the amount, so the answer is '
          f'actionable rather than a refusal',
          g['needed'] > 0 and g['symbol'] and str(g['needed']) in g['reason'])
    check(f'{chain}: ...and it does not claim to be gasless', g['gasless'] is False)

check('a funded Base wallet can bridge', R['gas_base_funded']['required'] is False)
check('a funded Solana wallet can bridge', R['gas_solana_funded']['required'] is False)

check('the origin leg of a bridge is NOT gasless on any chain, and the code '
      'says so rather than discovering it at signing time — 0x Gasless covers '
      'same-chain EVM swaps, which is a different transaction',
      all(R[k]['gasless'] is False for k in
          ('gas_base_empty', 'gas_solana_empty', 'gas_bsc_empty',
           'gas_base_funded', 'gas_solana_funded')))


# ── no subsidy, checked against the source ───────────────────────────────
# Read through app_entry, the real entrypoint, in its own process.
# dashboard.py's own default for this variable is ON; app_entry is what pins
# it off before dashboard is imported. So checking dashboard alone would be
# testing a value production never runs with, and the entrypoint would look
# like decoration when it is load-bearing.
_entry_probe = subprocess.run(
    [sys.executable, '-c',
     'import app_entry, dashboard; print("FRONTS=%r" % dashboard.ORCAGENT_FRONTS_GAS)'],
    cwd=REPO, env=env, capture_output=True, text=True, timeout=300)
check('app_entry pins ORCAGENT_FRONTS_GAS off before dashboard is imported, '
      'which is what makes the no-subsidy rule true in production — '
      'dashboard\'s own default is ON, so the entrypoint is load-bearing',
      'FRONTS=False' in _entry_probe.stdout)
check('...and imported on its own, dashboard would have fronted gas — stated '
      'so the line in app_entry is never "tidied up" as redundant',
      R['fronts_gas_direct'] is True)
check('the gas check contains no branch that spends a platform wallet — there '
      'is no sponsor, no hot wallet and no top-up in it, because a bridge '
      'OrcAgent pays for is a cost that never stops',
      not any(w in R['gas_src'] for w in
              ('GAS_SPONSOR_PRIVATE_KEY', '_sponsor_evm_gas', '_ensure_evm_gas',
               '_ensure_solana_gas')))
check('...and neither does the origin-leg sender', 
      not any(w in R['sender_src'] for w in
              ('GAS_SPONSOR_PRIVATE_KEY', '_sponsor_evm_gas')))


# ── Robinhood ────────────────────────────────────────────────────────────
check('Robinhood Chain\'s dollar asset is still called what it is — USDG, not '
      'USDC. A unified dollar balance in the UI is not a reason for the '
      'backend to forget which asset it holds',
      R['hood_stable'] == 'USDG')
check('...and its decimals are still unverified, so the registry refuses to '
      'guess them', R['hood_decimals'] is None)
check('...so no Robinhood cross-chain route is enabled: bridging an asset '
      'whose decimals nobody has confirmed is a sizing error waiting to '
      'happen', R['hood_enabled'] is False)


# ── the Solana fee stays honest ──────────────────────────────────────────
check('the Solana platform fee is still quoted at zero, because none is '
      'collected there — cross-chain work is not an excuse to quietly '
      'reintroduce a fee the user does not pay',
      R['solana_fee_rate'] == '0')

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
