"""Reservations, idempotency and the trade state machine.

Three failures these exist to make impossible, all of which look like
success from the outside:

  * two trades started at once both spend the same balance
  * a retried request produces a second swap, bridge and fee
  * a trade writes a state history that never happened, which later
    reconciliation then trusts

The concurrency check runs real threads against a real SQLite file, because
a race is not something a mock can demonstrate.
"""
import os
import sqlite3
import sys
import tempfile
import threading
import time
from decimal import Decimal

sys.path.insert(0, '/home/user/Orc-agent-Solana-chain-')

from trade_engine import ledger as L                          # noqa: E402
from trade_engine.costs import CostLine, KIND_BRIDGE_FEE, KIND_SOURCE_GAS  # noqa: E402

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

D = Decimal
DB = tempfile.mktemp(suffix='.db')

conn = sqlite3.connect(DB)
conn.execute('PRAGMA journal_mode=WAL')
L.ensure_schema(conn)

check('the schema creates cleanly', True)
L.ensure_schema(conn)
check('...and applying it twice is a no-op, so it is safe on every start', True)


def a_quote(quote_id='q1', can_execute=1, expires_in=30, same_chain=1, user_id=7):
    now = time.time()
    conn.execute(
        'INSERT OR REPLACE INTO trade_quotes (quote_id, user_id, wallet, mode, '
        'source_chain, destination_chain, token_address, max_spend_usd, '
        'token_purchase_usd, total_cost_usd, subsidy_usd, route, same_chain, '
        'can_execute, breakdown_json, created_at, expires_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (quote_id, user_id, 'W', 'manual', 'base', 'base', '0xtok', '100',
         '97.92', '100.00', '0', 'base USDC -> 0x', same_chain, can_execute,
         '{}', now, now + expires_in))
    conn.commit()
    return L.load_quote(conn, quote_id)


# ════════════════════════════════════════════════════════════════
# 1. A quote may only be executed while it is still true
# ════════════════════════════════════════════════════════════════
q = a_quote()
ok, why = L.quote_is_usable(q)
check('a fresh executable quote is usable', ok and why is None)

ok, why = L.quote_is_usable(a_quote('q_exp', expires_in=-1))
check('an expired quote is refused', not ok and 'expired' in why)

ok, why = L.quote_is_usable(a_quote('q_bad', can_execute=0))
check('a quote that was never executable stays un-executable', not ok)

ok, why = L.quote_is_usable(None)
check('a quote that does not exist is refused rather than crashing', not ok)

ok, why = L.quote_is_usable(q, now=q['expires_at'] + 1)
check('expiry is judged against the STORED expiry — the point of an expiry is '
      'that it does not move once a number has been shown', not ok)


# ════════════════════════════════════════════════════════════════
# 2. Idempotency is a database constraint, not a check
# ════════════════════════════════════════════════════════════════
tid1, created1 = L.start_execution(conn, idempotency_key='key-A', quote_row=q)
check('a first execution creates a trade', created1 and tid1)

tid2, created2 = L.start_execution(conn, idempotency_key='key-A', quote_row=q)
check('the SAME key returns the SAME trade and creates nothing — a retry must '
      'never produce a second swap, bridge or fee',
      tid2 == tid1 and created2 is False)

tid3, created3 = L.start_execution(conn, idempotency_key='key-B', quote_row=q)
check('a different key is a different trade', tid3 != tid1 and created3)

# Concurrent identical requests: exactly one may win.
results, errors = [], []
def racer():
    c = sqlite3.connect(DB, timeout=30)
    try:
        results.append(L.start_execution(c, idempotency_key='key-RACE', quote_row=q))
    except Exception as e:
        errors.append(e)
    finally:
        c.close()

threads = [threading.Thread(target=racer) for _ in range(8)]
for t in threads: t.start()
for t in threads: t.join()
created_count = sum(1 for _, c in results if c)
same_trade = len({tid for tid, _ in results}) == 1
check('eight identical requests at once create exactly ONE trade — the uniqueness '
      'is enforced by the schema, so the losers collide instead of racing past a '
      'lookup', created_count == 1 and not errors)
check('...and every one of them is handed back the same trade id', same_trade)


# ════════════════════════════════════════════════════════════════
# 3. The state machine
# ════════════════════════════════════════════════════════════════
tid = tid1
for state in (L.QUOTED, L.ROUTE_SELECTED, L.RESERVED, L.EXECUTING, L.SWAPPING,
              L.CONFIRMING, L.COMPLETED):
    L.transition(conn, tid, state)
check('a same-chain trade walks CREATED -> ... -> COMPLETED without ever bridging',
      L.get_trade(conn, tid)['state'] == L.COMPLETED)

try:
    L.transition(conn, tid, L.EXECUTING); ok = False
except L.IllegalTransition as e:
    ok = 'already finished' in str(e)
check('a completed trade cannot go back to executing', ok)

t_cross, _ = L.start_execution(conn, idempotency_key='key-X',
                               quote_row=a_quote('q_cross', same_chain=0))
L.transition(conn, t_cross, L.QUOTED)
L.transition(conn, t_cross, L.ROUTE_SELECTED)
L.transition(conn, t_cross, L.RESERVED)
L.transition(conn, t_cross, L.EXECUTING)
L.transition(conn, t_cross, L.BRIDGING)
check('a cross-chain trade may enter BRIDGING', L.get_trade(conn, t_cross)['state'] == L.BRIDGING)

t_same, _ = L.start_execution(conn, idempotency_key='key-Y', quote_row=a_quote('q_s2'))
L.transition(conn, t_same, L.QUOTED)
L.transition(conn, t_same, L.ROUTE_SELECTED)
L.transition(conn, t_same, L.RESERVED)
L.transition(conn, t_same, L.EXECUTING)
try:
    L.transition(conn, t_same, L.BRIDGING); ok = False
except L.IllegalTransition as e:
    ok = 'same-chain' in str(e)
check('a SAME-chain trade cannot report BRIDGING — that is either an unpriced '
      'route or a false record, and both need to raise', ok)

try:
    L.transition(conn, t_same, 'MADE_UP'); ok = False
except L.IllegalTransition:
    ok = True
check('a state that does not exist is refused', ok)

try:
    L.transition(conn, t_same, L.COMPLETED); ok = False
except L.IllegalTransition:
    ok = True
check('skipping straight from EXECUTING to COMPLETED is refused — a trade cannot '
      'be complete before it has confirmed', ok)

# REQUOTE_REQUIRED is a detour, not a death.
t_rq, _ = L.start_execution(conn, idempotency_key='key-Z', quote_row=a_quote('q_rq'))
L.transition(conn, t_rq, L.QUOTED)
L.transition(conn, t_rq, L.REQUOTE_REQUIRED)
L.transition(conn, t_rq, L.QUOTED)
check('a stale quote sends the trade to REQUOTE_REQUIRED and it can carry on from '
      'there — a moved price is not a failed trade',
      L.get_trade(conn, t_rq)['state'] == L.QUOTED)

L.transition(conn, t_rq, L.FAILED, failure_reason='provider down',
             needs_investigation=1)
tr = L.get_trade(conn, t_rq)
check('a failure records its reason and can be flagged for a human',
      tr['failure_reason'] == 'provider down' and tr['needs_investigation'] == 1)

try:
    L.transition(conn, t_cross, L.SWAPPING, wallet='someone-else'); ok = False
except L.LedgerError:
    ok = True
check('a transition cannot quietly rewrite fields it has no business touching, '
      'like the wallet the trade belongs to', ok)


# ════════════════════════════════════════════════════════════════
# 4. Reservations — the money two trades would otherwise both spend
# ════════════════════════════════════════════════════════════════
USER = 42
L.reserve(conn, user_id=USER, chain='base', trade_id='t-a',
          amount_usd=D('100'), available_usd=D('250'))
check('a reservation is taken', L.held_usd(conn, USER, 'base') == D('100'))

L.reserve(conn, user_id=USER, chain='base', trade_id='t-b',
          amount_usd=D('100'), available_usd=D('250'))
check('a second reservation fits in what is left', L.held_usd(conn, USER, 'base') == D('200'))

try:
    L.reserve(conn, user_id=USER, chain='base', trade_id='t-c',
              amount_usd=D('100'), available_usd=D('250'))
    ok = False
except L.InsufficientAvailable as e:
    ok = 'already reserved by another trade' in str(e)
check('a third is refused — the balance is there, but another trade has already '
      'claimed it, and the message says exactly that', ok)

L.reserve(conn, user_id=USER, chain='bsc', trade_id='t-d',
          amount_usd=D('200'), available_usd=D('200'))
check('reservations are per chain — a claim on Base does not block BSC',
      L.held_usd(conn, USER, 'bsc') == D('200'))

released = L.settle(conn, 't-a', D('97.92'))
check('a trade that came in under its reservation gives the difference back',
      released == D('2.08'))
check('...and the hold drops to what was really spent',
      L.held_usd(conn, USER, 'base') == D('100'))

released = L.release(conn, 't-b')
check('a trade that never executed releases its whole claim', released == D('100'))
check('...leaving nothing held on that chain', L.held_usd(conn, USER, 'base') == D('0'))

try:
    L.settle(conn, 't-b', D('1')); ok = False
except L.LedgerError as e:
    ok = 'already' in str(e)
check('a reservation cannot be settled twice — double-releasing would credit the '
      'user money they actually spent', ok)

L.reserve(conn, user_id=USER, chain='base', trade_id='t-e',
          amount_usd=D('50'), available_usd=D('100'))
released = L.settle(conn, 't-e', D('60'))
check('a trade that somehow spent MORE than it reserved releases nothing, rather '
      'than a negative amount', released == D('0'))

# The race the reservation exists for.
race_errors, race_ok = [], []
def spender():
    c = sqlite3.connect(DB, timeout=30)
    try:
        c.execute('PRAGMA busy_timeout=30000')
        L.reserve(c, user_id=99, chain='base', trade_id=f'race-{threading.get_ident()}',
                  amount_usd=D('60'), available_usd=D('100'))
        race_ok.append(1)
    except L.InsufficientAvailable:
        race_errors.append(1)
    except Exception as e:
        race_errors.append(e)
    finally:
        c.close()

threads = [threading.Thread(target=spender) for _ in range(6)]
for t in threads: t.start()
for t in threads: t.join()
check('six trades racing for $60 out of a $100 balance: exactly ONE wins — this '
      'is the check-then-act race the reservation exists to close',
      len(race_ok) == 1 and len(race_errors) == 5)
check('...and the ledger agrees afterwards', L.held_usd(conn, 99, 'base') == D('60'))


# ════════════════════════════════════════════════════════════════
# 5. Cost drift, per kind
# ════════════════════════════════════════════════════════════════
L.record_costs(conn, tid, 'quoted', [
    CostLine(KIND_SOURCE_GAS, D('0.35'), source='rpc'),
    CostLine(KIND_BRIDGE_FEE, D('1.20'), source='bridge'),
])
L.record_costs(conn, tid, 'actual', [
    CostLine(KIND_SOURCE_GAS, D('0.55'), source='rpc'),
    CostLine(KIND_BRIDGE_FEE, D('1.00'), source='bridge'),
])
drift = L.cost_drift(conn, tid)
check('gas that came in higher than quoted is visible as its own drift',
      abs(drift[KIND_SOURCE_GAS]['drift'] - 0.20) < 1e-9)
check('...and a bridge that came in cheaper as its own',
      abs(drift[KIND_BRIDGE_FEE]['drift'] + 0.20) < 1e-9)
check('reporting drift PER KIND is the point: these two cancel to zero in a '
      'total, and the expensive gas is the half worth knowing about',
      round(sum(v['drift'] for v in drift.values()), 9) == 0)

try:
    L.record_costs(conn, tid, 'guessed', []); ok = False
except L.LedgerError:
    ok = True
check('costs can only be recorded as quoted or actual', ok)


# ════════════════════════════════════════════════════════════════
# 6. Still no execution anywhere
# ════════════════════════════════════════════════════════════════
import ast, trade_engine.ledger as _l                          # noqa: E402
tree = ast.parse(open(_l.__file__).read())
imported = set()
for n in ast.walk(tree):
    if isinstance(n, ast.Import):
        imported.update(a.name.split('.')[0] for a in n.names)
    elif isinstance(n, ast.ImportFrom) and n.module:
        imported.add(n.module.split('.')[0])
for forbidden in ('dashboard', 'requests', 'web3'):
    check(f'the ledger does not import {forbidden}', forbidden not in imported)
check('the ledger opens no connection of its own — it is handed one, so it can '
      'never quietly write to a different database',
      'sqlite3.connect' not in open(_l.__file__).read())

conn.close()
os.unlink(DB)
print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
