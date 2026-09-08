"""Executing a quoted trade: once, within the ceiling, and never a false success.

Three rules carry the whole phase, and each has a test that fails loudly if
it stops holding:

  the swap sells the PURCHASE, not the amount the user typed;
  a retry with the same key never reaches the executor a second time;
  a transaction that was sent but not confirmed is not a completed trade.

The fourth thing worth proving is what happens to the money when something
goes wrong halfway: a swap that never went out gives its claim back, and a
swap that may have gone out keeps it, because releasing a balance that is
possibly already spent is how the same money gets spent twice.
"""
import os
import sqlite3
import sys
import tempfile
import time
from decimal import Decimal

sys.path.insert(0, '/home/user/Orc-agent-Solana-chain-')

from trade_engine import execute as X                             # noqa: E402
from trade_engine import ledger as L                              # noqa: E402
from trade_engine import subsidy as S                             # noqa: E402
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
conn.execute('''CREATE TABLE gas_sponsorships (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
    wallet TEXT NOT NULL, chain TEXT NOT NULL, to_address TEXT NOT NULL,
    amount_native REAL NOT NULL, amount_usd REAL DEFAULT 0, tx_hash TEXT DEFAULT '',
    status TEXT DEFAULT 'sent', error_msg TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
conn.commit()
S.apply_migrations(conn)


# ── a real quote, priced by the real engine, stored the real way ──
def fake_0x(sell, buy, amount, taker, chain):
    return {'buyAmount': '1000000000000000000', 'minBuyAmount': '985000000000000000',
            'transaction': {'gas': '200000', 'gasPrice': '10000000'}}


def make_quote(max_spend='100', user_id=1, clock=time.time, gas=D('0.35')):
    q = build_quote(
        QuoteRequest(user_id=user_id, wallet='W1', source_chain='base',
                     destination_chain='base', token_address='0xTOKEN',
                     max_spend_usd=D(max_spend), taker_address='0xTAKER'),
        swap_provider=ZeroExProvider(fake_0x),
        gas_estimator=lambda c: gas,
        fee_rate=D('0.0075'),
        gas_is_sponsored=lambda c: True,
        clock=clock,
    )
    L.save_quote(conn, q)
    return q


class Recorder:
    """An executor that says yes, and remembers exactly what it was asked."""
    def __init__(self, **outcome):
        self.calls = []
        self.outcome = outcome

    def __call__(self, plan):
        self.calls.append(plan)
        return X.SwapOutcome(submitted=True, confirmed=True, tx_hash='0xTX',
                             **self.outcome)


# ── RULE 1: the swap sells the purchase, not the ceiling ──
q = make_quote('100')
ex = Recorder()
r = X.execute_trade(conn, quote_id=q.quote_id, idempotency_key='k1',
                    available_usd=D('500'), swap_executor=ex)
plan = ex.calls[0]
check('the trade completes', r.state == L.COMPLETED and r.to_dict()['completed'])
check('the executor is told to swap the PURCHASE, which is less than the $100 the '
      'user entered — the amount every legacy endpoint swaps today',
      plan.purchase_usd < D('100') and plan.purchase_usd == D(q.to_dict()['token_purchase_usd']))
check('...and is handed the ceiling too, so it can assert instead of trusting '
      'that someone upstream subtracted', plan.max_spend_usd == D('100'))
check('purchase plus fee plus gas never exceeds the ceiling',
      plan.purchase_usd + plan.fee_usd + plan.gas_usd <= D('100'))
check('the fee is the one from the quote, not a fresh percentage of the ceiling',
      plan.fee_usd == D(q.to_dict()['costs_by_kind']['platform_fee']))
check('the executor never receives a private key, a signer or a connection — the '
      'plan is data', not any(k in plan.__dataclass_fields__ for k in
                              ('private_key', 'signer', 'conn', 'key')))


# ── the money is claimed and settled ──
res = conn.execute("SELECT status, amount_usd FROM balance_reservations WHERE trade_id=?",
                   (r.trade_id,)).fetchone()
check('the reservation is settled once the trade completes', res[0] == 'settled')
check('...at what the trade actually cost', D(res[1]) == D(q.to_dict()['total_user_spend_usd']))
check('nothing is left held for this user afterwards',
      L.held_usd(conn, 1, 'base') == D('0'))


# ── RULE 2: a retry sends nothing ──
q2 = make_quote('100')
ex2 = Recorder()
a = X.execute_trade(conn, quote_id=q2.quote_id, idempotency_key='same-key',
                    available_usd=D('500'), swap_executor=ex2)
b = X.execute_trade(conn, quote_id=q2.quote_id, idempotency_key='same-key',
                    available_usd=D('500'), swap_executor=ex2)
check('a retry with the same idempotency key returns the SAME trade',
      a.trade_id == b.trade_id)
check('...and the executor was called exactly once — no second swap, no second fee',
      len(ex2.calls) == 1)
check('...and the retry says so rather than pretending it did the work',
      b.created is False and 'nothing was sent a second time' in b.warnings[0])
check('a different key on the same quote is a different trade',
      X.execute_trade(conn, quote_id=q2.quote_id, idempotency_key='other-key',
                      available_usd=D('500'), swap_executor=ex2).trade_id != a.trade_id)


# ── RULE 3: submitted is not completed ──
q3 = make_quote('100')
r3 = X.execute_trade(
    conn, quote_id=q3.quote_id, idempotency_key='k3', available_usd=D('500'),
    swap_executor=lambda p: X.SwapOutcome(submitted=True, confirmed=False,
                                          tx_hash='0xMAYBE', error='receipt timed out'))
check('a swap that was sent but never confirmed is NOT a completed trade',
      r3.state == L.FAILED)
check('...it keeps the transaction hash, because something is out there',
      r3.tx_hash == '0xMAYBE')
check('...and is flagged for a human rather than filed away',
      r3.needs_investigation)
res3 = conn.execute("SELECT status, amount_usd FROM balance_reservations WHERE trade_id=?",
                    (r3.trade_id,)).fetchone()
check('...and its claim is SETTLED, not released: money that may already have left '
      'the wallet must not be handed to the next trade to spend again',
      res3[0] == 'settled' and D(res3[1]) > 0)


# ── a swap that provably never went out gives the money back ──
q4 = make_quote('100')
r4 = X.execute_trade(
    conn, quote_id=q4.quote_id, idempotency_key='k4', available_usd=D('500'),
    swap_executor=lambda p: X.SwapOutcome(submitted=False, confirmed=False,
                                          error='router rejected the trade'))
check('a swap that was never sent fails with the real reason',
      r4.state == L.FAILED and 'router rejected' in r4.failure_reason)
check('...its claim is RELEASED in full — nothing left the wallet',
      conn.execute("SELECT status FROM balance_reservations WHERE trade_id=?",
                   (r4.trade_id,)).fetchone()[0] == 'released')
check('...and it is not flagged, because nothing is unresolved',
      not r4.needs_investigation)


# ── a swap that landed and reverted: resolved, not ambiguous ──
q4b = make_quote('100', user_id=6)
r4b = X.execute_trade(
    conn, quote_id=q4b.quote_id, idempotency_key='k4b', available_usd=D('500'),
    swap_executor=lambda p: X.SwapOutcome(submitted=True, confirmed=False, reverted=True,
                                          tx_hash='0xREVERT',
                                          error='Swap transaction reverted on-chain'))
check('a swap that reverted on-chain is a failure with its hash kept — the '
      'transaction is real, it just did not do anything',
      r4b.state == L.FAILED and r4b.tx_hash == '0xREVERT')
check('...and is NOT flagged: a revert is a resolved outcome, unlike a timeout',
      not r4b.needs_investigation)
res4b = conn.execute("SELECT status, amount_usd FROM balance_reservations WHERE trade_id=?",
                     (r4b.trade_id,)).fetchone()
check('...and only the GAS stays claimed, because that is the only money that '
      'left the wallet — holding the whole $100 would lock up a balance the '
      'user still has',
      res4b[0] == 'settled' and D(res4b[1]) == D(q4b.to_dict()['costs_by_kind']['source_gas']))

check('a reverted swap and an unconfirmed one are told apart, which the legacy '
      'path cannot do at all — it throws the hash away on a receipt timeout',
      r4b.needs_investigation != r3.needs_investigation)


# ── an executor that raises is the ambiguous case, and is treated as such ──
def boom(plan):
    raise RuntimeError('RPC died mid-send')

q5 = make_quote('100')
r5 = X.execute_trade(conn, quote_id=q5.quote_id, idempotency_key='k5',
                     available_usd=D('500'), swap_executor=boom)
check('an executor that raises fails the trade rather than escaping to the caller',
      r5.state == L.FAILED and 'RPC died' in r5.failure_reason)
check('...and is flagged, since a raise can still have broadcast',
      r5.needs_investigation)
check('...keeping its claim for the same reason',
      conn.execute("SELECT status FROM balance_reservations WHERE trade_id=?",
                   (r5.trade_id,)).fetchone()[0] == 'settled')


# ── the money has to be there, and only once ──
q6 = make_quote('100', user_id=7)
ex6 = Recorder()
r6 = X.execute_trade(conn, quote_id=q6.quote_id, idempotency_key='k6',
                     available_usd=D('10'), swap_executor=ex6)
check('a trade larger than the balance is refused BEFORE the executor sees it',
      r6.state == L.FAILED and not ex6.calls)
check('...with the real numbers in the reason', '$10' in r6.failure_reason)

# two trades, one balance
qa, qb = make_quote('100', user_id=8), make_quote('100', user_id=8)
held = []
def slow(plan):
    # A second trade arrives while this one is in flight.
    held.append(X.execute_trade(conn, quote_id=qb.quote_id, idempotency_key='kb',
                                available_usd=D('150'),
                                swap_executor=lambda p: X.SwapOutcome(submitted=True, confirmed=True, tx_hash='0xB')))
    return X.SwapOutcome(submitted=True, confirmed=True, tx_hash='0xA')

ra = X.execute_trade(conn, quote_id=qa.quote_id, idempotency_key='ka',
                     available_usd=D('150'), swap_executor=slow)
check('two trades against one $150 balance: the first completes',
      ra.state == L.COMPLETED)
check('...and the second is refused, because the first already claimed the money — '
      'a balance check alone would have let both through',
      held[0].state == L.FAILED and 'already reserved by another trade' in held[0].failure_reason)


# ── the fee cannot undo a confirmed swap ──
q7 = make_quote('100', user_id=9)
r7 = X.execute_trade(
    conn, quote_id=q7.quote_id, idempotency_key='k7', available_usd=D('500'),
    swap_executor=lambda p: X.SwapOutcome(submitted=True, confirmed=True, tx_hash='0xFEE'),
    fee_charger=lambda p, o: X.FeeOutcome(charged=False, error='fee wallet out of gas'))
check('a fee that fails after a confirmed swap does NOT fail the trade — the swap '
      'happened, and rewriting that would be a false record', r7.state == L.COMPLETED)
check('...the uncollected fee is surfaced as a warning',
      any('fee was not collected' in w for w in r7.warnings))
check('...the trade is flagged so the debt is not lost', r7.needs_investigation)
costs = {(k, ph): u for k, ph, u in conn.execute(
    'SELECT kind, phase, usd FROM trade_costs WHERE trade_id=?', (r7.trade_id,))}
check('...and the actual fee is recorded as zero with the reason, not as if it '
      'had been paid', costs[('platform_fee', 'actual')] == '0')

# a fee charger that raises is the same debt, not a crash
q8 = make_quote('100', user_id=10)
def fee_boom(p, o):
    raise RuntimeError('fee transfer reverted')
r8 = X.execute_trade(conn, quote_id=q8.quote_id, idempotency_key='k8',
                     available_usd=D('500'),
                     swap_executor=lambda p: X.SwapOutcome(submitted=True, confirmed=True, tx_hash='0xF2'),
                     fee_charger=fee_boom)
check('a fee charger that raises is caught and recorded, never re-runs the swap',
      r8.state == L.COMPLETED and any('reverted' in w for w in r8.warnings))


# ── a fee that was dispatched but not yet collected ──
q8b = make_quote('100', user_id=17)
r8b = X.execute_trade(
    conn, quote_id=q8b.quote_id, idempotency_key='k8b', available_usd=D('500'),
    swap_executor=lambda p: X.SwapOutcome(submitted=True, confirmed=True, tx_hash='0xF3'),
    fee_charger=lambda p, o: X.FeeOutcome(charged=False, pending=True, usd=p.fee_usd))
check('a fee handed to a background transfer is reported as pending, not as '
      'collected — asserting a collection nobody has seen is the same false '
      'success this engine refuses everywhere else',
      r8b.state == L.COMPLETED and not r8b.needs_investigation)
c8b = {(k, ph): (u, dt) for k, ph, u, dt in conn.execute(
    'SELECT kind, phase, usd, detail FROM trade_costs WHERE trade_id=?', (r8b.trade_id,))}
check('...and the fee is still recorded at its full amount, because the USER\'s '
      'budget did pay it — whether OrcAgent collected it is a separate question',
      D(c8b[('platform_fee', 'actual')][0]) == D(q8b.to_dict()['costs_by_kind']['platform_fee'])
      and 'dispatched' in c8b[('platform_fee', 'actual')][1])

try:
    X.FeeOutcome(charged=True, pending=True)
    ok = False
except X.ExecutionError:
    ok = True
check('a fee cannot claim to be both collected and pending', ok)


# ── costs: quoted and actual, side by side ──
q9 = make_quote('100', user_id=11)
r9 = X.execute_trade(conn, quote_id=q9.quote_id, idempotency_key='k9',
                     available_usd=D('500'),
                     swap_executor=lambda p: X.SwapOutcome(submitted=True, confirmed=True, tx_hash='0xC',
                                       actual_gas_usd=D('0.55')))
drift = L.cost_drift(conn, r9.trade_id)
check('gas that came in above the quote shows as drift on that cost alone',
      round(drift['source_gas']['drift'], 2) == 0.20)
check('the slippage reserve is quoted but never written as an actual cost — it was '
      'held back, not spent',
      drift['slippage_reserve']['quoted'] > 0 and drift['slippage_reserve']['actual'] == 0.0)

r10 = X.execute_trade(
    conn, quote_id=make_quote('100', user_id=12).quote_id, idempotency_key='k10',
    available_usd=D('500'),
    swap_executor=lambda p: X.SwapOutcome(submitted=True, confirmed=True, tx_hash='0xD',
                                          actual_spend_usd=D('120')))
check('a trade that came in over its quote says so instead of absorbing it',
      any('above the' in w for w in r10.warnings))


# ── the gas grant is charged back ──
conn.execute("INSERT INTO gas_sponsorships (user_id, wallet, chain, to_address, "
             "amount_native, amount_usd, status) VALUES (13,'W','base','0x',0.001,0.35,'sent')")
conn.commit()
gid = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
q11 = make_quote('100', user_id=13)
r11 = X.execute_trade(conn, quote_id=q11.quote_id, idempotency_key='k11',
                      available_usd=D('500'),
                      swap_executor=lambda p: X.SwapOutcome(submitted=True, confirmed=True,
                                        tx_hash='0xG', gas_sponsorship_id=gid))
rep = S.subsidy_report(conn)
check('a sponsored grant tied to a completed trade is charged to that trade',
      conn.execute('SELECT trade_id FROM gas_sponsorships WHERE id=?',
                   (gid,)).fetchone()[0] == r11.trade_id)
check('...so it adds nothing to the outstanding subsidy — the whole point of phase 4',
      rep['outstanding_usd'] == '0.00' and rep['tracked_grants'] == 1)


# ── a quote that may not be executed ──
try:
    X.execute_trade(conn, quote_id='nope', idempotency_key='kx',
                    available_usd=D('500'), swap_executor=Recorder())
    ok = False
except X.QuoteNotUsable:
    ok = True
check('an unknown quote is refused', ok)

past = make_quote('100', clock=lambda: time.time() - 3600)
ex_stale = Recorder()
try:
    X.execute_trade(conn, quote_id=past.quote_id, idempotency_key='kstale',
                    available_usd=D('500'), swap_executor=ex_stale)
    ok = False
except X.QuoteNotUsable:
    ok = True
check('an expired quote is refused before anything is started — a price the user '
      'saw a minute ago is not a price they agreed to now', ok and not ex_stale.calls)
check('...and no trade row was created for it',
      conn.execute("SELECT COUNT(*) FROM trade_executions WHERE idempotency_key='kstale'"
                   ).fetchone()[0] == 0)


# ── an inconsistent stored quote is not executed ──
bad = make_quote('100', user_id=14)
conn.execute("UPDATE trade_quotes SET token_purchase_usd='999' WHERE quote_id=?",
             (bad.quote_id,))
conn.commit()
ex_bad = Recorder()
r_bad = X.execute_trade(conn, quote_id=bad.quote_id, idempotency_key='kbad',
                        available_usd=D('5000'), swap_executor=ex_bad)
check('a stored quote whose parts exceed its own ceiling is refused rather than '
      'overspending a user who was shown a smaller number',
      r_bad.state == L.FAILED and not ex_bad.calls and r_bad.needs_investigation)
check('...and its claim is released', conn.execute(
    "SELECT status FROM balance_reservations WHERE trade_id=?",
    (r_bad.trade_id,)).fetchone()[0] == 'released')


# ── crash recovery ──
q12 = make_quote('100', user_id=15)
tid, _ = L.start_execution(conn, idempotency_key='kcrash', quote_row=L.load_quote(conn, q12.quote_id))
L.transition(conn, tid, L.QUOTED); L.transition(conn, tid, L.ROUTE_SELECTED)
L.reserve(conn, user_id=15, chain='base', trade_id=tid, amount_usd=D('50'),
          available_usd=D('500'), now=time.time() - 4000)
freed = X.reap_stale_reservations(conn, older_than_seconds=900)
check('a claim abandoned before execution is released so the balance is usable again',
      tid in freed and L.held_usd(conn, 15, 'base') == D('0'))

q13 = make_quote('100', user_id=16)
tid2, _ = L.start_execution(conn, idempotency_key='kcrash2', quote_row=L.load_quote(conn, q13.quote_id))
for st in (L.QUOTED, L.ROUTE_SELECTED):
    L.transition(conn, tid2, st)
L.reserve(conn, user_id=16, chain='base', trade_id=tid2, amount_usd=D('50'),
          available_usd=D('500'), now=time.time() - 4000)
L.transition(conn, tid2, L.RESERVED); L.transition(conn, tid2, L.EXECUTING)
L.transition(conn, tid2, L.SWAPPING)
check('a claim on a trade that was MID-SWAP when the process died is left alone — '
      'that money may be in flight, and freeing it is how it gets spent twice',
      tid2 not in X.reap_stale_reservations(conn, older_than_seconds=900)
      and L.held_usd(conn, 16, 'base') == D('50'))


# ── the engine stays an engine ──
import ast                                                        # noqa: E402
src = open('/home/user/Orc-agent-Solana-chain-/trade_engine/execute.py').read()
tree = ast.parse(src)
imported = set()
for n in ast.walk(tree):
    if isinstance(n, ast.Import):
        imported.update(a.name.split('.')[0] for a in n.names)
    elif isinstance(n, ast.ImportFrom) and n.module:
        imported.add(n.module.split('.')[0])
for forbidden in ('dashboard', 'requests', 'web3', 'flask', 'solders'):
    check(f'the execution engine does not import {forbidden}', forbidden not in imported)
check('it opens no connection of its own', 'sqlite3.connect' not in src)
for word in ('private_key', 'decrypt', 'ZEROX_API_KEY'):
    check(f'...and never handles {word}', word not in src)

conn.close()
os.unlink(DB)
print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
