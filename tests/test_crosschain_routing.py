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
from decimal import Decimal

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

# ── the economic guard, against the REAL live route ──
import json as _json, os as _os
_fx_path = _os.path.join(_os.path.dirname(_os.path.dirname(d.__file__)),
                         'social-multi-trading-chain-', 'tests', 'fixtures',
                         '0x', 'quote_base_to_solana.json')
if not _os.path.isfile(_fx_path):
    _fx_path = 'tests/fixtures/0x/quote_base_to_solana.json'
out['econ'] = {}
from decimal import Decimal as _D
if _os.path.isfile(_fx_path):
    _fx = _json.load(open(_fx_path))
    _data = _json.loads(_json.dumps(_fx['response']))
    # The capture now carries the REAL transaction at full length, so nothing
    # is rebuilt here: the economic check below runs behind the same calldata
    # validation a live trade would, on the same bytes 0x sent. The amount
    # asked for is the amount the capture was taken at -- ask for a different
    # one and the calldata check refuses the route first, which is the
    # safety gate doing its job rather than an obstacle to work around.
    _amount = _D(str(_fx['amount_usd']))
    d.TRADE_ENGINE_CROSSCHAIN = True
    d.CROSSCHAIN_ENABLED_ROUTES = frozenset({'base->solana'})
    d._cc_taker_address = lambda w, c: (_fx['destination_address'] if c == 'solana'
                                        else _fx['origin_address'])
    d._te_crosschain_provider = lambda: d.te_crosschain.ZeroExCrossChain(
        lambda **k: _data, lambda **k: {})
    _q = d._te_bridge_quoter('W', 'econ-key')
    # At the default 5% ceiling the real $30 route is ALLOWED: $0.56 is 1.9%.
    try:
        _r = _q('base', 'solana', _amount)
        out['econ']['at_default'] = str(_r['fee_usd'])
        out['econ']['at_default_pct'] = str(
            (_D(str(_r['fee_usd'])) / _amount * 100).quantize(_D('0.01')))
    except Exception as _e:
        out['econ']['at_default'] = 'refused: ' + str(_e)
    # Tighten the ceiling below what this route costs and the same route is
    # refused, with the real numbers in the message.
    _orig_pct = d.CROSSCHAIN_MAX_BRIDGE_COST_PCT
    d.CROSSCHAIN_MAX_BRIDGE_COST_PCT = 1.0
    try:
        _q2 = d._te_bridge_quoter('W', 'econ-key-tight')
        _q2('base', 'solana', _amount)
        out['econ']['tight_limit'] = 'allowed'
    except Exception as _e:
        out['econ']['tight_limit'] = str(_e)
    d.CROSSCHAIN_MAX_BRIDGE_COST_PCT = _orig_pct
out['econ_default_pct'] = d.CROSSCHAIN_MAX_BRIDGE_COST_PCT

# ── the resume worker must outlive the flag ──
# An empty database has nothing to finish; one with a bridge in flight does,
# and that is true whether or not the route is open.
out['unfinished_empty'] = d._crosschain_unfinished_count()
import sqlite3 as _sq, time as _t
_c = _sq.connect(d.DB_FILE)
_c.execute("INSERT INTO trade_executions (trade_id, idempotency_key, quote_id, "
           "user_id, wallet, mode, state, same_chain, max_spend_usd, created_at, "
           "updated_at) VALUES ('t-cc','k-cc','q-cc',1,'W','manual','BRIDGING',0,"
           "'30',?,?)", (_t.time(), _t.time()))
_c.execute("INSERT INTO trade_crosschain (trade_id, quote_id, user_id, provider, "
           "source_chain, destination_chain, source_token, destination_token, "
           "source_amount_raw, created_at, updated_at) VALUES ('t-cc','q-cc',1,'0x',"
           "'base','solana','0xUSDC','SolUSDC','30000000',?,?)", (_t.time(), _t.time()))
_c.commit(); _c.close()
out['unfinished_after'] = d._crosschain_unfinished_count()

# ── where the money is, at each ending ──
_filled = {'provider_status': 'bridge_filled', 'destination_tx_hash': '0xDEST',
           'actual_out_raw': '29700000'}
_nothing = {'provider_status': 'origin_tx_pending', 'destination_tx_hash': '',
            'actual_out_raw': ''}
out['loc'] = {
    'failed_after_bridge': d._cc_funds_location('FAILED', _filled, 'solana', 'base'),
    'failed_before_bridge': d._cc_funds_location('FAILED', _nothing, 'solana', 'base'),
    'completed': d._cc_funds_location('COMPLETED', _filled, 'solana', 'base'),
    'manual': d._cc_funds_location('MANUAL_REVIEW', _filled, 'solana', 'base'),
    'refunded': d._cc_funds_location('REFUNDED', _nothing, 'solana', 'base'),
    'bridging': d._cc_funds_location('BRIDGING', _nothing, 'solana', 'base'),
}
# Each mark on its own is enough: a row written before one of them existed
# still answers correctly through the others.
out['delivered_by'] = [
    d._cc_bridge_delivered({'provider_status': 'bridge_filled'}),
    d._cc_bridge_delivered({'destination_tx_hash': '0xD'}),
    d._cc_bridge_delivered({'actual_out_raw': '1'}),
    d._cc_bridge_delivered({}),
]

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


# ── the economics of the real live route ─────────────────────────────────
# The first live Base -> Solana quote priced a $2 bridge at $0.22 -- safe, and
# still a bad trade, because a bridge's costs are largely fixed and eleven
# percent was a fact about the SIZE rather than about the route. The live $30
# capture is the other end of that same sentence: $0.56, 1.9%, allowed. So
# what is pinned here is the THRESHOLD behaving in both directions on real
# numbers, rather than a route being permanently blessed or banned.
econ = R.get('econ') or {}
if econ:
    check('the real $30 Base -> Solana bridge is ALLOWED at the default 5% '
          'ceiling, and costs $0.56 — the same route that ate 11% of $2',
          econ.get('at_default') == '0.56')
    check('...which is under two percent of the trade, so the ceiling is doing '
          'nothing here except standing ready',
          Decimal(econ.get('at_default_pct') or '0') < Decimal('2'))
    check('...and it is a threshold, not a blessing: tighten the ceiling below '
          'what this route costs and the SAME route is refused, with the real '
          'cost and percentage in the message',
          '0.56' in econ.get('tight_limit', '')
          and '1.9%' in econ.get('tight_limit', ''))
    check('...and the refusal tells the user what to do about it rather than '
          'just saying no',
          'larger amount' in econ.get('tight_limit', '')
          or 'bigger trade' in econ.get('tight_limit', ''))
check('the default ceiling is a percentage of the trade, so a bridge that is '
      'ruinous on $2 is unremarkable on $200',
      float(R['econ_default_pct']) == 5.0)


# ── the resume worker outlives the flag ──────────────────────────────────
# The controlled live test runs with cross-chain OFF, by design. If the worker
# only ever started with the flag, a trade left in BRIDGING by that test -- a
# real transaction on chain, with the user's claim still held -- would sit
# there until somebody thought to turn a feature on. The same applies to
# closing a route while a bridge is in flight.
check('an empty database has no unfinished cross-chain work, so a deployment '
      'that will never bridge still starts no worker',
      R['unfinished_empty'] == 0)
check('...while a trade left in BRIDGING counts as work this database owes, '
      'whatever the flag says', R['unfinished_after'] == 1)

# ── where the user's money is, when a trade ends badly ───────────────────
# "Trade failed" is the same two words whether nothing left Base or the
# bridge worked and only the purchase did not. In the second case the user's
# dollars are USDC on Solana, and if nobody says so they will look for them
# on Base.
loc = R.get('loc') or {}
check('a trade that failed AFTER the bridge delivered says the dollars are on '
      'the destination chain, and names it',
      loc['failed_after_bridge']['where'] == 'destination'
      and 'Solana' in loc['failed_after_bridge']['note'])
check('...while one that failed BEFORE anything left says the opposite, so the '
      'two are never confused',
      loc['failed_before_bridge']['where'] == 'source'
      and 'Nothing left' in loc['failed_before_bridge']['note'])
check('a completed trade says nothing extra — the money is in the token, and '
      'there is nothing for a user to go looking for',
      loc['completed']['where'] == 'spent' and loc['completed']['note'] == '')
check('MANUAL_REVIEW does NOT guess a location. That state exists because '
      'what happened could not be established, and inventing an answer there '
      'is worse than saying a person is looking',
      loc['manual']['where'] == 'unknown'
      and 'has not been lost' in loc['manual']['note'])
check('a refund says the money is back where it started', 
      loc['refunded']['where'] == 'source' and 'Base' in loc['refunded']['note'])
check('a bridge in flight claims nothing, because in flight is exactly what '
      'it is', loc['bridging']['where'] == 'in_flight'
      and loc['bridging']['note'] == '')
check('delivery is recognised by any of the three marks a row can carry, and '
      'by none of them on an empty row',
      R['delivered_by'] == [True, True, True, False])

_src = open(REPO + '/dashboard.py').read()
check('...and the worker starts on either — the feature being on, OR money '
      'already in flight. A flag going off must not strand a bridge',
      'if TRADE_ENGINE_CROSSCHAIN or _cc_unfinished:' in _src)
check('...and says so in the log when it starts for that second reason, '
      'because a worker running while the feature is off would otherwise read '
      'as a bug', 'even though cross-chain is off' in _src)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
