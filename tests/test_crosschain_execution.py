"""A cross-chain trade, interrupted at every point it can be interrupted.

WHAT THIS IS ACTUALLY TESTING
Not that a bridge works -- that is 0x's job and it cannot be proven from
here. What it tests is that OrcAgent never loses track of a user's money,
whatever happens to the process in the middle.

The restart tests all take the same shape: run a trade to some state, THROW
AWAY every object, reopen the database, and hand the trade id to the resume
function as if a fresh process had just booted and found it. If the engine
kept anything in memory that mattered, these fail. Each one then checks the
two things a restart must never change: the reservation is still held, and
nothing is sent twice.

The database is real. Only the two things that touch the outside world -- the
provider's status endpoint and the destination swap -- are stubbed.
"""
import os
import sqlite3
import sys
import tempfile
import time
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trade_engine import execute as E               # noqa: E402
from trade_engine import ledger as L                # noqa: E402
from trade_engine import crosschain as X            # noqa: E402
from trade_engine import registry as R              # noqa: E402

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

D = Decimal
# One database FILE per scenario. held_usd() sums every outstanding claim a
# user has on a chain, so scenarios sharing a database would see each other's
# reservations and the numbers below would be about the test, not the engine.
_DBDIR = tempfile.mkdtemp()
_DB = {'path': ''}
UID = 7


def fresh_db():
    _DB['path'] = os.path.join(_DBDIR, f'cc{len(os.listdir(_DBDIR))}.db')
    return db()
WALLET = '0x1111111111111111111111111111111111111111'
TOKEN = 'TokenMint5555555555555555555555555555555555'

BASE_USDC = R.CHAINS['base'].stable.address
SOL_USDC = R.CHAINS['solana'].stable.address


def db():
    conn = sqlite3.connect(_DB['path'])
    L.ensure_schema(conn)
    return conn


class FakeRoute:
    provider = '0x'
    quote_id = 'quote-1'          # 0x's per-quote quoteId
    zid = 'zid-1'                 # 0x's top-level request id — a different thing
    source_token = BASE_USDC
    destination_token = SOL_USDC
    source_amount_raw = 100_000_000
    expected_out_raw = 99_500_000
    minimum_out_raw = 99_000_000
    estimated_seconds = 45
    fees_raw = {'zeroExFee': {'amount': '100000'}}
    raw = {}


def make_quote(conn, *, quote_id, max_spend='100', purchase='97.50',
               total='100', same_chain=0, src='base', dst='solana'):
    """A stored quote, written the way save_quote() writes one."""
    import json
    body = {
        'token_purchase_usd': purchase, 'total_user_spend_usd': total,
        'orcagent_subsidy_usd': '0', 'can_execute': True,
        'costs_by_kind': {'bridge_fee': '1.00', 'source_gas': '0.50',
                          'destination_gas': '0.50', 'platform_fee': '0.50'},
        'minimum_output_raw': '1000',
    }
    conn.execute(
        'INSERT OR REPLACE INTO trade_quotes (quote_id, user_id, wallet, mode, '
        'source_chain, destination_chain, token_address, max_spend_usd, '
        'token_purchase_usd, total_cost_usd, subsidy_usd, route, same_chain, '
        'can_execute, breakdown_json, created_at, expires_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (quote_id, UID, WALLET, 'manual', src, dst, TOKEN, max_spend, purchase,
         total, '0', f'{src}->bridge->{dst}', same_chain, 1, json.dumps(body),
         time.time(), time.time() + 3600))
    conn.commit()
    return L.load_quote(conn, quote_id)


def sender_ok(tx='0xSRC'):
    calls = []
    def send(route):
        calls.append(route)
        return E.SourceOutcome(submitted=True, tx_hash=tx)
    send.calls = calls
    return send


def status_of(status, **kw):
    seen = {}
    def fetch(chain, tx, quote_id=''):
        seen['quote_id'] = quote_id
        return X.CrossChainStatus(
            status=status,
            source_on_chain=status in X.SOURCE_IS_ON_CHAIN,
            filled=status == X.BRIDGE_FILLED,
            failed=status in (X.BRIDGE_FAILED, X.ORIGIN_REVERTED),
            destination_tx_hash=kw.get('dest', ''),
            settled_out_raw=kw.get('settled'),
            failure_reason=kw.get('reason', ''),
            recovery=kw.get('recovery', {}))
    fetch.seen = seen
    return fetch


def swap_ok(tx='0xSWAP'):
    calls = []
    def run(plan):
        calls.append(plan)
        return E.SwapOutcome(submitted=True, confirmed=True, tx_hash=tx)
    run.calls = calls
    return run


def held(conn):
    return L.held_usd(conn, UID, 'base')


# ═════════════════════════════════════════════════════════════════════════
#  the ordinary path
# ═════════════════════════════════════════════════════════════════════════
conn = fresh_db()
q = make_quote(conn, quote_id='q1')
send = sender_ok()
r = E.start_crosschain_trade(conn, quote_id='q1', idempotency_key='k1',
                             available_usd=D('500'), route=FakeRoute(),
                             source_sender=send)
T1 = r.trade_id
check('starting a cross-chain trade stops at BRIDGING — it does not block an '
      'HTTP request for the minutes a bridge takes, and does not pretend to '
      'be finished', r.state == L.BRIDGING and not r.finished)
check('...having broadcast the origin transaction exactly once', len(send.calls) == 1)
check('...and the claim on the user\'s money is STILL HELD, because the money '
      'is in flight and nothing about it is settled', held(conn) == D('100'))
check('the reservation is taken on the SOURCE chain, which is where the money '
      'leaves from — reserving on the destination would claim against a '
      'balance this trade never touches',
      L.held_usd(conn, UID, 'solana') == D('0'))

cc = L.get_crosschain(conn, T1)
check('every identifier needed to pick this trade up again is persisted',
      cc['provider_quote_id'] == 'quote-1' and cc['source_tx_hash'] == '0xSRC'
      and cc['source_chain'] == 'base' and cc['destination_chain'] == 'solana'
      and cc['minimum_out_raw'] == '99000000' and float(cc['source_sent_at']) > 0)

# bridge still moving
r = E.resume_crosschain_trade(conn, trade_id=T1,
                              status_fetcher=status_of('bridge_pending'),
                              dest_swap_executor=swap_ok())
check('a bridge still in flight stays in BRIDGING and keeps the claim',
      r.state == L.BRIDGING and held(conn) == D('100'))

# funds land, swap runs
swap = swap_ok()
r = E.resume_crosschain_trade(
    conn, trade_id=T1,
    status_fetcher=status_of('bridge_filled', dest='DESTTX', settled=99_400_000),
    dest_swap_executor=swap)
check('once the bridge fills, the destination swap runs and the trade completes',
      r.state == L.COMPLETED)
check('...the swap was told to buy on the DESTINATION chain',
      swap.calls and swap.calls[0].chain == 'solana')
check('...it sells the PURCHASE the quote settled on, not the ceiling',
      swap.calls and swap.calls[0].purchase_usd == D('97.50'))
check('...and only now is the claim released', held(conn) == D('0'))
cc = L.get_crosschain(conn, T1)
check('the amount that actually arrived is recorded next to the amount that '
      'was quoted — reconciliation needs both, and they are not the same',
      cc['actual_out_raw'] == '99400000' and cc['quoted_out_raw'] == '99500000')
check('the destination swap transaction is persisted separately from the '
      'bridge\'s own', cc['swap_tx_hash'] == '0xSWAP' and cc['destination_tx_hash'] == 'DESTTX')
conn.close()


# ═════════════════════════════════════════════════════════════════════════
#  idempotency
# ═════════════════════════════════════════════════════════════════════════
conn = fresh_db()
make_quote(conn, quote_id='q2')
send = sender_ok('0xSRC2')
a = E.start_crosschain_trade(conn, quote_id='q2', idempotency_key='same-key',
                             available_usd=D('500'), route=FakeRoute(),
                             source_sender=send)
b = E.start_crosschain_trade(conn, quote_id='q2', idempotency_key='same-key',
                             available_usd=D('500'), route=FakeRoute(),
                             source_sender=send)
check('a duplicate execute request returns the SAME trade',
      a.trade_id == b.trade_id and b.created is False)
check('...and never builds a second bridge — one origin transaction, whatever '
      'the caller does', len(send.calls) == 1)
check('...and does not double-claim the balance', held(conn) == D('100'))

# and the cross-chain row itself is a second, independent guard
opened_again = L.open_crosschain(
    conn, trade_id=a.trade_id, quote_id='q2', user_id=UID, provider='0x',
    source_chain='base', destination_chain='solana', source_token=BASE_USDC,
    destination_token=SOL_USDC, source_amount_raw=1)
check('the cross-chain leg has its own database-level guard: a second attempt '
      'to open one for the same trade LOSES, rather than being told to check '
      'first and then racing', opened_again is False)
conn.close()


# ═════════════════════════════════════════════════════════════════════════
#  restarts
# ═════════════════════════════════════════════════════════════════════════
def restart_at(quote_id, *, stop_state, status_fetcher=None, swap=None,
               sender=None):
    """Run a trade to `stop_state`, then drop everything and reopen."""
    conn = fresh_db()
    make_quote(conn, quote_id=quote_id)
    r = E.start_crosschain_trade(
        conn, quote_id=quote_id, idempotency_key='k-' + quote_id,
        available_usd=D('500'), route=FakeRoute(),
        source_sender=sender or sender_ok('0x' + quote_id))
    tid = r.trade_id
    if stop_state != L.BRIDGING and r.state == L.BRIDGING:
        conn.execute('UPDATE trade_executions SET state=? WHERE trade_id=?',
                     (stop_state, tid))
        conn.commit()
    conn.close()                      # ── the process dies here ──
    fresh = db()                      # ── and a new one boots ──
    return fresh, tid


# 14. restart during AWAITING_SOURCE, with the origin tx recorded
conn, tid = restart_at('q3', stop_state=L.AWAITING_SOURCE)
swap = swap_ok()
r = E.resume_crosschain_trade(conn, trade_id=tid,
                              status_fetcher=status_of('bridge_pending'),
                              dest_swap_executor=swap)
check('a restart mid-send, where the origin transaction WAS recorded, picks '
      'the trade up and carries on watching the bridge',
      r.state == L.BRIDGING and held(conn) == D('100'))
check('...and does not re-send anything', not swap.calls)
conn.close()

# 14b. restart during AWAITING_SOURCE with NO hash — the dangerous one
conn = fresh_db()
make_quote(conn, quote_id='q4')
r = E.start_crosschain_trade(
    conn, quote_id='q4', idempotency_key='k4', available_usd=D('500'),
    route=FakeRoute(),
    source_sender=lambda route: E.SourceOutcome(submitted=True, tx_hash='0xq4'))
tid = r.trade_id
conn.execute("UPDATE trade_executions SET state=? WHERE trade_id=?",
             (L.AWAITING_SOURCE, tid))
conn.execute("UPDATE trade_crosschain SET source_tx_hash='' WHERE trade_id=?", (tid,))
conn.commit(); conn.close()
conn = db()
r = E.resume_crosschain_trade(conn, trade_id=tid,
                              status_fetcher=status_of('bridge_pending'),
                              dest_swap_executor=swap_ok())
check('a restart mid-send with NO recorded transaction does NOT retry: whether '
      'something was broadcast cannot be established from here, and retrying '
      'would bridge the user\'s money a second time',
      r.state == L.MANUAL_REVIEW)
check('...and the claim is kept, because releasing it would let the next trade '
      'spend money that may already be in flight', held(conn) == D('100'))
conn.close()

# 15. restart during BRIDGING
conn, tid = restart_at('q5', stop_state=L.BRIDGING)
r = E.resume_crosschain_trade(conn, trade_id=tid,
                              status_fetcher=status_of('bridge_pending'),
                              dest_swap_executor=swap_ok())
check('a restart during BRIDGING resumes from the database, with no memory of '
      'the process that started it', r.state == L.BRIDGING)
check('...and the reservation survived the restart — a process restarting is '
      'not information about where the money went', held(conn) == D('100'))
conn.close()

# 16. restart after the destination funds arrived
conn, tid = restart_at('q6', stop_state=L.BRIDGING)
swap = swap_ok('0xAFTER')
r = E.resume_crosschain_trade(
    conn, trade_id=tid,
    status_fetcher=status_of('bridge_filled', dest='DT', settled=99_000_000),
    dest_swap_executor=swap)
check('a restart that finds the funds already delivered runs the destination '
      'swap and finishes the trade', r.state == L.COMPLETED and len(swap.calls) == 1)
conn.close()

# 20. restart during SWAPPING, swap hash recorded
conn, tid = restart_at('q7', stop_state=L.BRIDGING)
E.resume_crosschain_trade(conn, trade_id=tid,
                          status_fetcher=status_of('bridge_filled', dest='DT'),
                          dest_swap_executor=lambda p: (_ for _ in ()).throw(
                              RuntimeError('process died')))
state_after = L.get_trade(conn, tid)['state']
check('a destination swap that may have been sent leaves the trade for a '
      'person rather than guessing, and keeps the claim',
      state_after == L.MANUAL_REVIEW and held(conn) == D('100'))
conn.close()


# ═════════════════════════════════════════════════════════════════════════
#  failures
# ═════════════════════════════════════════════════════════════════════════
# origin reverted: nothing left the source chain, so everything goes back
conn, tid = restart_at('q8', stop_state=L.BRIDGING)
r = E.resume_crosschain_trade(conn, trade_id=tid,
                              status_fetcher=status_of('origin_tx_reverted'),
                              dest_swap_executor=swap_ok())
check('an origin transaction that reverted releases the WHOLE claim — nothing '
      'left the source chain, so none of it is spent',
      r.state == L.FAILED and held(conn) == D('0'))
conn.close()

# bridge failed after the origin succeeded: the money is owed back
conn, tid = restart_at('q9', stop_state=L.BRIDGING)
r = E.resume_crosschain_trade(
    conn, trade_id=tid,
    status_fetcher=status_of('bridge_failed', reason='no fill'),
    dest_swap_executor=swap_ok())
check('a bridge that failed AFTER the origin leg succeeded becomes a refund, '
      'not a plain failure — the money is real and somebody owes it back',
      r.state == L.REFUND_PENDING)
check('...and the claim is kept while it is owed', held(conn) == D('100'))
r = E.resume_crosschain_trade(
    conn, trade_id=tid,
    status_fetcher=status_of('bridge_failed', recovery={'refundTxHash': '0xrf'}),
    dest_swap_executor=swap_ok())
check('once the refund lands the trade is REFUNDED and only the gas that was '
      'genuinely spent is settled — the rest is the user\'s again',
      r.state == L.REFUNDED and held(conn) == D('0'))
conn.close()

# a bridge that never settles
conn, tid = restart_at('q10', stop_state=L.BRIDGING)
r = E.resume_crosschain_trade(conn, trade_id=tid,
                              status_fetcher=status_of('bridge_pending'),
                              dest_swap_executor=swap_ok(),
                              deadline_seconds=-1)
check('a bridge past its deadline stops being "slow" and becomes something a '
      'person has to find — with the claim still held, because the money is '
      'on chain somewhere', r.state == L.MANUAL_REVIEW and held(conn) == D('100'))
conn.close()

# provider unreachable after broadcast
conn, tid = restart_at('q11', stop_state=L.BRIDGING)
def boom(chain, tx, quote_id=''):
    raise RuntimeError('provider timeout')
r = E.resume_crosschain_trade(conn, trade_id=tid, status_fetcher=boom,
                              dest_swap_executor=swap_ok())
check('not being able to ask the provider is not news about the money: the '
      'trade stays where it is and is asked again later',
      r.state == L.BRIDGING and held(conn) == D('100'))
conn.close()

# destination swap fails cleanly after a successful bridge
conn, tid = restart_at('q12', stop_state=L.BRIDGING)
r = E.resume_crosschain_trade(
    conn, trade_id=tid, status_fetcher=status_of('bridge_filled', dest='DT'),
    dest_swap_executor=lambda p: E.SwapOutcome(
        submitted=False, confirmed=False, error='no route on the destination'))
check('a destination swap that was never sent releases the claim: the bridge '
      'worked, so the user holds USDC on the far chain — not what they asked '
      'for, but safe and theirs', r.state == L.FAILED and held(conn) == D('0'))
conn.close()


# ═════════════════════════════════════════════════════════════════════════
#  the ceiling, and what the reaper may touch
# ═════════════════════════════════════════════════════════════════════════
conn = fresh_db()
make_quote(conn, quote_id='q13', max_spend='100', purchase='97.50', total='100')
r = E.start_crosschain_trade(conn, quote_id='q13', idempotency_key='k13',
                             available_usd=D('500'), route=FakeRoute(),
                             source_sender=sender_ok('0x13'))
check('what is claimed is the whole authorised amount, never more — $100 '
      'authorised claims exactly $100, and the purchase inside it is smaller',
      held(conn) == D('100'))
conn.close()

conn = fresh_db()
make_quote(conn, quote_id='q14')
send14 = sender_ok('0x14')
r = E.start_crosschain_trade(conn, quote_id='q14', idempotency_key='k14',
                             available_usd=D('50'), route=FakeRoute(),
                             source_sender=send14)
check('a balance that cannot cover the trade fails it', r.state == L.FAILED)
check('...before anything is signed, which is the point — a bridge that gets '
      'halfway on money the user does not have is the expensive version of '
      'this check', not send14.calls)
check('...and holds nothing afterwards', held(conn) == D('0'))
conn.close()

# the reaper must not touch a bridge in flight
conn, tid = restart_at('q15', stop_state=L.BRIDGING)
freed = E.reap_stale_reservations(conn, older_than_seconds=-1)
check('the stale-reservation reaper does NOT free a bridge in flight, however '
      'old it is — that claim is on money that is somewhere between two '
      'chains, and releasing it is how the same balance gets spent twice',
      tid not in freed and held(conn) == D('100'))
check('...and the trade is left in BRIDGING for the resume worker, not failed',
      L.get_trade(conn, tid)['state'] == L.BRIDGING)

# ...and resumable_crosschain finds exactly it
found = [row['trade_id'] for row in L.resumable_crosschain(conn)]
check('a restart finds the unfinished trade by querying the database for it, '
      'which is the only place it exists after a process dies', tid in found)
conn.close()


# ═════════════════════════════════════════════════════════════════════════
#  a route with NO quoteId — which is what the live API actually returns
# ═════════════════════════════════════════════════════════════════════════
# The first live quote from production came back with quoteId_present=false.
# 0x's published status schema takes only originChain and originTxHash, and
# its own example sends only those two, so a route without a quoteId is not a
# degraded case -- it is the documented one. What must not happen is the zid
# being sent in its place: that identifies the REQUEST, not the quote, and
# substituting one for the other is the confusion the two columns exist to
# prevent.
class NoQuoteIdRoute(FakeRoute):
    quote_id = ''          # exactly what the live response gave
    zid = 'ZID-LIVE-9'     # present, and NOT a quote id


conn = fresh_db()
make_quote(conn, quote_id='q17')
send17 = sender_ok('0xNOQID')
r = E.start_crosschain_trade(conn, quote_id='q17', idempotency_key='k17',
                             available_usd=D('500'), route=NoQuoteIdRoute(),
                             source_sender=send17)
T17 = r.trade_id
check('a route with no quoteId still executes — that is the shape the live '
      'API returns, not a broken one', r.state == L.BRIDGING)

cc17 = L.get_crosschain(conn, T17)
check('...the empty quote id is stored as empty', cc17['provider_quote_id'] == '')
check('...and the zid is stored SEPARATELY rather than filling in for it — a '
      'request id under the name "quote id" is what the split exists to stop',
      cc17['provider_zid'] == 'ZID-LIVE-9')

st17 = status_of('bridge_pending')
E.resume_crosschain_trade(conn, trade_id=T17, status_fetcher=st17,
                          dest_swap_executor=swap_ok())
check('...and the status lookup sends NO quote id, falling back to the pair '
      '0x actually documents',
      st17.seen.get('quote_id') == '')
check('...and the zid is never sent as one', st17.seen.get('quote_id') != 'ZID-LIVE-9')

# ...and the trade still finishes end to end without one.
st17b = status_of('bridge_filled', dest='DT17', settled=99_000_000)
swap17 = swap_ok('0xSWAP17')
r = E.resume_crosschain_trade(conn, trade_id=T17, status_fetcher=st17b,
                              dest_swap_executor=swap17)
check('...and the trade completes without a quoteId ever existing',
      r.state == L.COMPLETED and len(swap17.calls) == 1)
check('...releasing the claim as normal', held(conn) == D('0'))
conn.close()


# ═════════════════════════════════════════════════════════════════════════
#  a same-chain quote must never take this path
# ═════════════════════════════════════════════════════════════════════════
conn = fresh_db()
make_quote(conn, quote_id='q16', same_chain=1, src='base', dst='base')
try:
    E.start_crosschain_trade(conn, quote_id='q16', idempotency_key='k16',
                             available_usd=D('500'), route=FakeRoute(),
                             source_sender=sender_ok())
    check('a same-chain quote cannot be executed as a bridge', False)
except E.ExecutionError:
    check('a same-chain quote cannot be executed as a bridge — it would record '
          'a journey the money never took', True)
conn.close()

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
