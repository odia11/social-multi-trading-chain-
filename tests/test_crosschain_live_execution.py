"""The real $30 route, driven through the real state machine.

WHAT THIS ADDS TO test_crosschain_execution.py
That file interrupts a trade at every point it can be interrupted, using a
FakeRoute whose numbers were invented to be easy to read. This one does the
ordinary path only, but with the ACTUAL route parsed out of the live capture
-- the real quoteId, the real zid, 30000000 of Base USDC, and the real 2954
characters of calldata.

WHY THAT IS WORTH A FILE OF ITS OWN
It is the last thing that can be proven before real money. Everything between
the response and the signature has been checked in pieces: the parser reads
it, the spender rules accept it, the calldata decodes to what the quote says.
What this checks is the join -- that the bytes reaching the sender are the
bytes 0x sent, unedited and unrebuilt, and that what gets written down about
the trade is the live quote's own identifiers rather than something derived
from them.

Nothing here signs, sends or spends. The origin sender and the destination
swap are stubs; the database is real.
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
from decimal import Decimal

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from trade_engine import execute as E               # noqa: E402
from trade_engine import ledger as L                # noqa: E402
from trade_engine import crosschain as X            # noqa: E402
from trade_engine import registry as R              # noqa: E402

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


FX = os.path.join(REPO, 'tests', 'fixtures', '0x', 'quote_base_to_solana.json')
if not os.path.isfile(FX):
    print('NOTE  the live Base -> Solana fixture is not present; nothing to drive.')
    sys.exit(0)

fx = json.load(open(FX))
data = fx['response']
q = data['quotes'][0]

D = Decimal
UID = 7
WALLET = '0x1111111111111111111111111111111111111111'
TOKEN = 'TokenMint5555555555555555555555555555555555'
BASE_USDC = R.CHAINS['base'].stable.address
SOL_USDC = R.CHAINS['solana'].stable.address

_DBDIR = tempfile.mkdtemp()
_DB = {'path': ''}


def fresh_db():
    _DB['path'] = os.path.join(_DBDIR, f'live{len(os.listdir(_DBDIR))}.db')
    conn = sqlite3.connect(_DB['path'])
    L.ensure_schema(conn)
    return conn


def reopen():
    """A brand new connection to the same file, as a restarted process gets."""
    conn = sqlite3.connect(_DB['path'])
    L.ensure_schema(conn)
    return conn


# ── the route, parsed from the live capture by the real parser ───────────
ROUTE = X.ZeroExCrossChain(lambda **kw: data, lambda **kw: {}).get_quote(
    source_chain='base', destination_chain='solana',
    source_amount_raw=30_000_000, origin_address=fx['origin_address'],
    destination_address=fx['destination_address'])

# It is verified before anything touches it, exactly as the engine does.
X.ZeroExCrossChain(lambda **kw: data, lambda **kw: {}).verify_route(
    ROUTE, expected_recipient=fx['destination_address'],
    expected_sender=fx['origin_address'])


def make_quote(conn, *, quote_id):
    """A stored quote carrying the live route's own numbers.

    $30 in, $0.56 to the bridge, and the rest of the ceiling spent on gas,
    the platform fee and the purchase -- the shape the quote builder
    produces, with the bridge line taken from the live capture rather than
    chosen to be convenient.
    """
    body = {
        'token_purchase_usd': '28.44', 'total_user_spend_usd': '30.00',
        'orcagent_subsidy_usd': '0', 'can_execute': True,
        'costs_by_kind': {'bridge_fee': '0.56', 'source_gas': '0.35',
                          'destination_gas': '0.20', 'platform_fee': '0.45'},
        'minimum_output_raw': str(ROUTE.minimum_out_raw),
    }
    conn.execute(
        'INSERT OR REPLACE INTO trade_quotes (quote_id, user_id, wallet, mode, '
        'source_chain, destination_chain, token_address, max_spend_usd, '
        'token_purchase_usd, total_cost_usd, subsidy_usd, route, same_chain, '
        'can_execute, breakdown_json, created_at, expires_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (quote_id, UID, WALLET, 'manual', 'base', 'solana', TOKEN, '30.00',
         '28.44', '30.00', '0', 'base->bridge->solana', 0, 1,
         json.dumps(body), time.time(), time.time() + 3600))
    conn.commit()
    return L.load_quote(conn, quote_id)


def sender_ok(tx='0xORIGIN'):
    seen = []
    def send(route):
        seen.append(route)
        return E.SourceOutcome(submitted=True, tx_hash=tx)
    send.seen = seen
    return send


def status_of(status, **kw):
    def fetch(chain, tx, quote_id=''):
        fetch.quote_id = quote_id
        return X.CrossChainStatus(
            status=status,
            source_on_chain=status in X.SOURCE_IS_ON_CHAIN,
            filled=status == X.BRIDGE_FILLED,
            failed=status in (X.BRIDGE_FAILED, X.ORIGIN_REVERTED),
            destination_tx_hash=kw.get('dest', ''),
            settled_out_raw=kw.get('settled'),
            failure_reason=kw.get('reason', ''),
            recovery=kw.get('recovery', {}))
    fetch.quote_id = None
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
#  the ordinary path, on the live route
# ═════════════════════════════════════════════════════════════════════════
conn = fresh_db()
make_quote(conn, quote_id='live-1')
send = sender_ok()
r = E.start_crosschain_trade(conn, quote_id='live-1', idempotency_key='live-k1',
                             available_usd=D('500'), route=ROUTE,
                             source_sender=send)
TID = r.trade_id

check('the live route starts a trade and stops at BRIDGING, holding the claim',
      r.state == L.BRIDGING and not r.finished and held(conn) == D('30.00'))
check('...on the SOURCE chain, which is where the $30 actually leaves from',
      L.held_usd(conn, UID, 'solana') == D('0'))
check('...having broadcast exactly once', len(send.seen) == 1)

# ── what the sender was handed ──
sent = send.seen[0]
check('the sender is handed the captured calldata UNCHANGED — 2954 characters, '
      'byte for byte what 0x returned. Nothing rebuilt it, shortened it or '
      'repaired it on the way through',
      sent.tx_data == q['transaction']['details']['data']
      and len(sent.tx_data) == 2954)
check('...addressed to the AllowanceHolder contract 0x named, with no value '
      'attached', sent.tx_to.lower() == data['allowanceTarget'].lower()
      and sent.tx_value == 0)
_dec = X.decode_allowance_holder_exec(sent.tx_data)
check('...and those bytes still decode to pulling exactly 30000000 of Base '
      'USDC, which is the whole blast radius of the transaction',
      _dec['token'].lower() == BASE_USDC.lower() and _dec['amount'] == 30_000_000)

# ── what was written down ──
cc = L.get_crosschain(conn, TID)
check('the trade records the live quoteId, and the top-level zid in its own '
      'column — the two identifiers stay apart in the database as well as in '
      'the parser',
      cc['provider_quote_id'] == '0x07dab35a87e2c7dc4f01b20f76f4c808'
      and cc['provider_zid'] == '0x07dab35a87e2c7dc4f01b20f'
      and cc['provider_quote_id'] != cc['provider_zid'])
check('...along with the amounts the live quote promised, so a settlement can '
      'later be compared against what was agreed rather than against a fresh '
      'quote at a different price',
      cc['source_amount_raw'] == '30000000'
      and cc['quoted_out_raw'] == '29744092'
      and cc['minimum_out_raw'] == '29446652')
check('...and the origin transaction hash, with the time it was sent',
      cc['source_tx_hash'] == '0xORIGIN' and float(cc['source_sent_at']) > 0)
check('...and both chains and both tokens, so a resumed process does not have '
      'to re-derive any of it',
      cc['source_chain'] == 'base' and cc['destination_chain'] == 'solana'
      and cc['source_token'].lower() == BASE_USDC.lower()
      and cc['destination_token'] == SOL_USDC)

# ═════════════════════════════════════════════════════════════════════════
#  a restart in the middle of the bridge
# ═════════════════════════════════════════════════════════════════════════
del conn, send
conn = reopen()
check('after a restart the trade is still there, still BRIDGING, and its claim '
      'is still held — the money is in flight and nothing about it is settled',
      L.get_trade(conn, TID)['state'] == L.BRIDGING
      and held(conn) == D('30.00'))
check('...and it is offered to the resume worker as resumable work',
      TID in [row['trade_id'] for row in L.resumable_crosschain(conn)])

fetch = status_of('bridge_pending')
r = E.resume_crosschain_trade(conn, trade_id=TID, status_fetcher=fetch,
                              dest_swap_executor=swap_ok())
check('a bridge still in flight keeps the trade in BRIDGING and the claim held',
      r.state == L.BRIDGING and held(conn) == D('30.00'))
check('...and the status is asked for by the live quoteId, which is the handle '
      '0x issued for this quote', fetch.quote_id ==
      '0x07dab35a87e2c7dc4f01b20f76f4c808')

# ═════════════════════════════════════════════════════════════════════════
#  the bridge fills
# ═════════════════════════════════════════════════════════════════════════
swap = swap_ok()
r = E.resume_crosschain_trade(
    conn, trade_id=TID,
    status_fetcher=status_of('bridge_filled', dest='0xDEST', settled=29_700_000),
    dest_swap_executor=swap)
check('once the bridge fills the destination swap runs and the trade completes',
      r.state == L.COMPLETED)
check('...the swap buys on SOLANA, with the purchase the quote settled on '
      'rather than the $30 ceiling',
      swap.calls and swap.calls[0].chain == 'solana'
      and swap.calls[0].purchase_usd == D('28.44'))
check('...and only now is the claim released', held(conn) == D('0'))

cc = L.get_crosschain(conn, TID)
check('what arrived is recorded next to what was quoted — 29700000 against '
      '29744092. Reconciliation needs both, and a bridge does not promise they '
      'are equal', cc['actual_out_raw'] == '29700000'
      and cc['quoted_out_raw'] == '29744092')
check('...and what arrived cleared the minimum the live quote guaranteed',
      int(cc['actual_out_raw']) >= int(cc['minimum_out_raw']))
check('...with the bridge\'s own destination transaction kept apart from the '
      'swap\'s', cc['destination_tx_hash'] == '0xDEST'
      and cc['swap_tx_hash'] == '0xSWAP')
conn.close()


# ═════════════════════════════════════════════════════════════════════════
#  the same live route cannot be bridged twice
# ═════════════════════════════════════════════════════════════════════════
conn = fresh_db()
make_quote(conn, quote_id='live-2')
send = sender_ok('0xONCE')
a = E.start_crosschain_trade(conn, quote_id='live-2', idempotency_key='same',
                             available_usd=D('500'), route=ROUTE,
                             source_sender=send)
b = E.start_crosschain_trade(conn, quote_id='live-2', idempotency_key='same',
                             available_usd=D('500'), route=ROUTE,
                             source_sender=send)
check('pressing execute twice on the live route returns the same trade and '
      'broadcasts once — with real calldata in hand, this is the check that '
      'stands between a double-click and two bridges',
      a.trade_id == b.trade_id and b.created is False and len(send.seen) == 1)
check('...and claims the $30 once, not twice', held(conn) == D('30.00'))
conn.close()

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
