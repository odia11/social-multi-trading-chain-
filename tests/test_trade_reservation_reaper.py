"""A claim left by a dead process must be given back — and only that one.

WHAT WAS HAPPENING
reserve() takes a claim on a user's balance before anything is sent, so two
trades cannot spend the same money (trade_engine/ledger.py). Normally
execute_trade() closes that claim at the end, whichever way the trade went.
A process killed in between -- a deploy, an OOM, a crash -- leaves it 'held'
with nobody left to close it, and held_usd() then subtracts it from that
user's free balance on every later trade. The money is still in their wallet.
The app just refuses to let them spend it, and nothing in the app ever gave
it back: reap_stale_reservations() has existed since the ledger was written
and was called from nowhere at all.

WHAT MUST NOT HAPPEN INSTEAD
Freeing every old claim. A trade that reached EXECUTING may have a swap in
flight, and handing that money back invites the next trade to spend it a
second time -- the exact double-spend the reservation exists to prevent. So
the reaper is deliberately narrow, and the test that matters most here is the
one proving it leaves those alone.
"""
import os
import sqlite3
import sys
import tempfile
import time
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trade_engine import execute as X                             # noqa: E402
from trade_engine import ledger as L                              # noqa: E402
from trade_engine.providers import ZeroExProvider                 # noqa: E402
from trade_engine.quote import QuoteRequest, build_quote          # noqa: E402

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

D = Decimal
DB = tempfile.mktemp(suffix='.db')
conn = sqlite3.connect(DB)
L.ensure_schema(conn)


def fake_0x(sell, buy, amount, taker, chain):
    return {'buyAmount': '1000000000000000000', 'minBuyAmount': '985000000000000000',
            'transaction': {'gas': '200000', 'gasPrice': '10000000'}}


def make_trade(user_id, states, *, age_seconds, amount='50'):
    """A trade walked to `states[-1]`, holding a claim `age_seconds` old."""
    q = build_quote(
        QuoteRequest(user_id=user_id, wallet=f'W{user_id}', source_chain='base',
                     destination_chain='base', token_address='0xTOKEN',
                     max_spend_usd=D(amount), taker_address='0xTAKER'),
        swap_provider=ZeroExProvider(fake_0x),
        gas_estimator=lambda c: D('0.35'), fee_rate=D('0.0075'))
    L.save_quote(conn, q)
    trade_id, _ = L.start_execution(conn, idempotency_key=f'k-{user_id}-{time.time()}',
                                    quote_row=L.load_quote(conn, q.quote_id))
    for s in states:
        L.transition(conn, trade_id, s)
    L.reserve(conn, user_id=user_id, chain='base', trade_id=trade_id,
              amount_usd=D(amount), available_usd=D('1000'))
    # Backdate the claim rather than waiting: the reaper's only input is age.
    conn.execute('UPDATE balance_reservations SET created_at=? WHERE trade_id=?',
                 (time.time() - age_seconds, trade_id))
    conn.commit()
    return trade_id


# ── the abandoned claim ───────────────────────────────────────────────────
abandoned = make_trade(1, [L.QUOTED, L.ROUTE_SELECTED, L.RESERVED], age_seconds=3600)
check('before the reaper runs, the dead trade is still holding the money',
      L.held_usd(conn, 1, 'base') == D('50'))

freed = X.reap_stale_reservations(conn, older_than_seconds=900)
check('the reaper frees a claim from a trade that never started executing',
      abandoned in freed)
check('...and the money is available to that user again',
      L.held_usd(conn, 1, 'base') == D('0'))
check('...with the trade recorded as failed rather than left looking live',
      (L.get_trade(conn, abandoned) or {}).get('state') == L.FAILED)


# ── the claim that must NOT be freed ──────────────────────────────────────
inflight = make_trade(2, [L.QUOTED, L.ROUTE_SELECTED, L.RESERVED, L.EXECUTING,
                          L.SWAPPING], age_seconds=3600)
freed2 = X.reap_stale_reservations(conn, older_than_seconds=900)
check('a trade that reached the swap keeps its claim however old it is — its '
      'money may be in flight, and giving it back is how the same balance '
      'gets spent twice', inflight not in freed2)
check('...so that user\'s balance stays held', L.held_usd(conn, 2, 'base') == D('50'))
check('...and the trade is not rewritten as failed behind its own back',
      (L.get_trade(conn, inflight) or {}).get('state') == L.SWAPPING)


# ── a claim too young to be abandoned ─────────────────────────────────────
recent = make_trade(3, [L.QUOTED, L.ROUTE_SELECTED, L.RESERVED], age_seconds=60)
freed3 = X.reap_stale_reservations(conn, older_than_seconds=900)
check('a claim younger than the cutoff is left alone — it belongs to a trade '
      'that is very likely still running', recent not in freed3)
check('...and keeps its money held', L.held_usd(conn, 3, 'base') == D('50'))


# ── the wiring: it has to actually run ────────────────────────────────────
DASH = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'dashboard.py'), encoding='utf-8').read()
check('the reaper is started as a background loop, not left as the dead code '
      'it was -- a recovery routine nobody calls recovers nothing',
      'threading.Thread(target=_trade_reservation_reap_loop, daemon=True).start()' in DASH)
check('...and the loop calls the narrow reaper rather than clearing claims '
      'itself', 'te_execute.reap_stale_reservations(' in DASH)
check('...on a cutoff comfortably longer than a quote lives, so it can only '
      'catch a process that is genuinely gone',
      'TRADE_RESERVATION_REAP_AFTER = 900' in DASH)
_loop_body = DASH[DASH.index('def _trade_reservation_reap_loop('):]
_loop_body = _loop_body[:_loop_body.index('\n@app.route')]
check('...and one bad cycle cannot kill the loop -- a reaper that dies on one '
      'bad row stops giving anyone their money back',
      'while True:' in _loop_body and 'except Exception' in _loop_body)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
