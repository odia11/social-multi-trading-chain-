"""What a trade is, from quoted to settled, and who has claimed what money.

Four tables and a state machine. No trade runs through any of this yet --
this is the record the execution phase will write to, built and tested
first so the accounting exists before anything moves money into it.

WHY A RESERVATION AND NOT A BALANCE CHECK
Two trades started a second apart both read the same balance and both decide
they can afford it. Nothing today prevents that, and the second one
discovers the problem on-chain. A reservation is a claim on money taken
BEFORE execution and inside a transaction, so the second trade sees the
first one's claim and refuses instead of overdrawing.

WHY IDEMPOTENCY IS A DATABASE CONSTRAINT AND NOT A CHECK
"Look up the key, and insert if absent" is two statements, and two identical
requests can both pass the lookup. The uniqueness is enforced by the schema,
so the loser of that race gets an IntegrityError and returns the existing
trade rather than starting a second one.

WHY TRANSITIONS ARE VALIDATED
A trade that goes from COMPLETED back to EXECUTING, or a same-chain trade
that reports BRIDGING, is a bug in the caller. Left unchecked it writes a
false history that later reconciliation trusts. An illegal transition raises.

Takes a sqlite3 connection; opens none of its own. No network, no app.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from decimal import Decimal
from typing import Optional


class LedgerError(Exception):
    pass


class IllegalTransition(LedgerError):
    pass


class InsufficientAvailable(LedgerError):
    """The money is there, but another trade has already claimed it."""


# ── states ───────────────────────────────────────────────────────────────
CREATED = 'CREATED'
QUOTED = 'QUOTED'
ROUTE_SELECTED = 'ROUTE_SELECTED'
RESERVED = 'RESERVED'
EXECUTING = 'EXECUTING'
BRIDGING = 'BRIDGING'
SWAPPING = 'SWAPPING'
CONFIRMING = 'CONFIRMING'
COMPLETED = 'COMPLETED'
FAILED = 'FAILED'
REQUOTE_REQUIRED = 'REQUOTE_REQUIRED'
CANCELLED = 'CANCELLED'

TERMINAL = frozenset({COMPLETED, FAILED, CANCELLED})

# Every legal move. Anything absent is a bug in the caller, not a state the
# trade can reach.
TRANSITIONS: dict = {
    CREATED: {QUOTED, FAILED, CANCELLED},
    QUOTED: {ROUTE_SELECTED, REQUOTE_REQUIRED, FAILED, CANCELLED},
    ROUTE_SELECTED: {RESERVED, REQUOTE_REQUIRED, FAILED, CANCELLED},
    RESERVED: {EXECUTING, REQUOTE_REQUIRED, FAILED, CANCELLED},
    EXECUTING: {BRIDGING, SWAPPING, FAILED},
    BRIDGING: {SWAPPING, REQUOTE_REQUIRED, FAILED},
    SWAPPING: {CONFIRMING, FAILED},
    CONFIRMING: {COMPLETED, FAILED},
    # A stale quote is not a dead trade: it can be re-quoted and carry on.
    REQUOTE_REQUIRED: {QUOTED, CANCELLED, FAILED},
    COMPLETED: set(),
    FAILED: set(),
    CANCELLED: set(),
}

SCHEMA = [
    # The quote as it was given, kept so execution can be validated against
    # the exact numbers the user agreed to rather than a fresh calculation.
    '''CREATE TABLE IF NOT EXISTS trade_quotes (
        quote_id            TEXT PRIMARY KEY,
        user_id             INTEGER NOT NULL,
        wallet              TEXT NOT NULL,
        mode                TEXT NOT NULL,
        source_chain        TEXT NOT NULL,
        destination_chain   TEXT NOT NULL,
        token_address       TEXT NOT NULL,
        max_spend_usd       TEXT NOT NULL,
        token_purchase_usd  TEXT NOT NULL,
        total_cost_usd      TEXT NOT NULL,
        subsidy_usd         TEXT NOT NULL,
        route               TEXT NOT NULL,
        same_chain          INTEGER NOT NULL,
        can_execute         INTEGER NOT NULL,
        breakdown_json      TEXT NOT NULL,
        created_at          REAL NOT NULL,
        expires_at          REAL NOT NULL
    )''',
    'CREATE INDEX IF NOT EXISTS idx_trade_quotes_user ON trade_quotes(user_id, created_at)',

    # One row per trade. idempotency_key is UNIQUE so a retry collides in
    # the database instead of racing past a lookup.
    '''CREATE TABLE IF NOT EXISTS trade_executions (
        trade_id            TEXT PRIMARY KEY,
        idempotency_key     TEXT NOT NULL UNIQUE,
        quote_id            TEXT NOT NULL,
        user_id             INTEGER NOT NULL,
        wallet              TEXT NOT NULL,
        mode                TEXT NOT NULL,
        state               TEXT NOT NULL,
        same_chain          INTEGER NOT NULL,
        max_spend_usd       TEXT NOT NULL,
        actual_spend_usd    TEXT DEFAULT '',
        actual_subsidy_usd  TEXT DEFAULT '',
        source_tx_hash      TEXT DEFAULT '',
        bridge_tx_hash      TEXT DEFAULT '',
        destination_tx_hash TEXT DEFAULT '',
        failure_reason      TEXT DEFAULT '',
        needs_investigation INTEGER DEFAULT 0,
        created_at          REAL NOT NULL,
        updated_at          REAL NOT NULL,
        FOREIGN KEY (quote_id) REFERENCES trade_quotes(quote_id)
    )''',
    'CREATE INDEX IF NOT EXISTS idx_trade_exec_user ON trade_executions(user_id, created_at)',
    'CREATE INDEX IF NOT EXISTS idx_trade_exec_state ON trade_executions(state)',

    # Quoted and actual side by side, per cost line, so a drift between them
    # is visible per cost rather than only in a total.
    '''CREATE TABLE IF NOT EXISTS trade_costs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id    TEXT NOT NULL,
        kind        TEXT NOT NULL,
        phase       TEXT NOT NULL,          -- 'quoted' | 'actual'
        usd         TEXT NOT NULL,
        payer       TEXT NOT NULL,
        source      TEXT NOT NULL,
        sponsored   INTEGER DEFAULT 0,
        detail      TEXT DEFAULT '',
        created_at  REAL NOT NULL
    )''',
    'CREATE INDEX IF NOT EXISTS idx_trade_costs_trade ON trade_costs(trade_id, phase)',

    # A claim on money, taken before execution and released after.
    '''CREATE TABLE IF NOT EXISTS balance_reservations (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL,
        chain       TEXT NOT NULL,
        trade_id    TEXT NOT NULL,
        amount_usd  TEXT NOT NULL,
        status      TEXT NOT NULL,          -- 'held' | 'settled' | 'released'
        created_at  REAL NOT NULL,
        closed_at   REAL DEFAULT NULL
    )''',
    'CREATE INDEX IF NOT EXISTS idx_reservations_held ON balance_reservations(user_id, chain, status)',
    'CREATE UNIQUE INDEX IF NOT EXISTS idx_reservations_trade ON balance_reservations(trade_id)',
]


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the tables if they are absent. Safe to call on every start."""
    for ddl in SCHEMA:
        conn.execute(ddl)
    conn.commit()


def _d(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


# ── quotes ───────────────────────────────────────────────────────────────
def save_quote(conn: sqlite3.Connection, priced_quote) -> str:
    """Persist a quote exactly as it was shown."""
    body = priced_quote.to_dict()
    r = priced_quote.request
    conn.execute(
        'INSERT OR REPLACE INTO trade_quotes (quote_id, user_id, wallet, mode, '
        'source_chain, destination_chain, token_address, max_spend_usd, '
        'token_purchase_usd, total_cost_usd, subsidy_usd, route, same_chain, '
        'can_execute, breakdown_json, created_at, expires_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (priced_quote.quote_id, r.user_id, r.wallet, r.mode, r.source_chain,
         r.destination_chain, r.token_address, str(r.max_spend_usd),
         body['token_purchase_usd'], body['total_user_spend_usd'],
         body['orcagent_subsidy_usd'], priced_quote.route,
         1 if priced_quote.same_chain else 0,
         1 if body['can_execute'] else 0, json.dumps(body),
         priced_quote.created_at, priced_quote.expires_at))
    conn.commit()
    return priced_quote.quote_id


def load_quote(conn: sqlite3.Connection, quote_id: str) -> Optional[dict]:
    row = conn.execute('SELECT * FROM trade_quotes WHERE quote_id=?', (quote_id,)).fetchone()
    if not row:
        return None
    cols = [c[0] for c in conn.execute('SELECT * FROM trade_quotes LIMIT 0').description]
    return dict(zip(cols, row))


def quote_is_usable(quote_row: dict, now: Optional[float] = None) -> tuple:
    """Whether a stored quote may still be executed, and why not.

    Checked against the stored expiry rather than a fresh calculation: the
    point of an expiry is that it does not move once the user has been shown
    a number.
    """
    if not quote_row:
        return False, 'That quote no longer exists. Request a new one.'
    if not quote_row['can_execute']:
        return False, 'That quote was not executable when it was made.'
    if (now if now is not None else time.time()) >= quote_row['expires_at']:
        return False, 'That quote has expired. Request a new one.'
    return True, None


# ── executions ───────────────────────────────────────────────────────────
def start_execution(conn: sqlite3.Connection, *, idempotency_key: str, quote_row: dict,
                    now: Optional[float] = None) -> tuple:
    """Claim an execution for this idempotency key.

    Returns (trade_id, created). `created` False means this key already
    started a trade and the existing one is returned -- a retry must never
    produce a second swap, a second bridge or a second fee.
    """
    ts = now if now is not None else time.time()
    trade_id = uuid.uuid4().hex
    try:
        conn.execute(
            'INSERT INTO trade_executions (trade_id, idempotency_key, quote_id, '
            'user_id, wallet, mode, state, same_chain, max_spend_usd, '
            'created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (trade_id, idempotency_key, quote_row['quote_id'], quote_row['user_id'],
             quote_row['wallet'], quote_row['mode'], CREATED,
             quote_row['same_chain'], quote_row['max_spend_usd'], ts, ts))
        conn.commit()
        return trade_id, True
    except sqlite3.IntegrityError:
        # The UNIQUE index did its job: another request with this key got
        # here first. Hand back the trade it started.
        conn.rollback()
        row = conn.execute(
            'SELECT trade_id FROM trade_executions WHERE idempotency_key=?',
            (idempotency_key,)).fetchone()
        if not row:
            raise LedgerError('idempotency collision with no existing trade')
        return row[0], False


def transition(conn: sqlite3.Connection, trade_id: str, to_state: str, *,
               now: Optional[float] = None, **fields) -> None:
    """Move a trade to a new state, or raise.

    Enforces two things the callers must not be trusted with: that the move
    is one the state machine allows, and that a same-chain trade never
    reports BRIDGING -- a same-chain trade that claims to have bridged has
    either taken a route nobody priced or is writing a false history.
    """
    row = conn.execute(
        'SELECT state, same_chain FROM trade_executions WHERE trade_id=?',
        (trade_id,)).fetchone()
    if not row:
        raise LedgerError(f'no trade {trade_id}')
    current, same_chain = row[0], bool(row[1])

    if to_state not in TRANSITIONS:
        raise IllegalTransition(f'{to_state} is not a state')
    if to_state not in TRANSITIONS[current]:
        raise IllegalTransition(
            f'{current} -> {to_state} is not a legal move'
            + (' (this trade is already finished)' if current in TERMINAL else '')
        )
    if to_state == BRIDGING and same_chain:
        raise IllegalTransition(
            'a same-chain trade cannot enter BRIDGING — it needs no bridge, so '
            'this is either an unpriced route or a false record'
        )

    allowed = {'actual_spend_usd', 'actual_subsidy_usd', 'source_tx_hash',
               'bridge_tx_hash', 'destination_tx_hash', 'failure_reason',
               'needs_investigation'}
    unknown = set(fields) - allowed
    if unknown:
        raise LedgerError(f'cannot set {sorted(unknown)} on a trade')

    sets = ['state=?', 'updated_at=?']
    args = [to_state, now if now is not None else time.time()]
    for k, v in fields.items():
        sets.append(f'{k}=?')
        args.append(str(v) if not isinstance(v, int) else v)
    args.append(trade_id)
    conn.execute(f'UPDATE trade_executions SET {", ".join(sets)} WHERE trade_id=?', args)
    conn.commit()


def get_trade(conn: sqlite3.Connection, trade_id: str) -> Optional[dict]:
    row = conn.execute('SELECT * FROM trade_executions WHERE trade_id=?', (trade_id,)).fetchone()
    if not row:
        return None
    cols = [c[0] for c in conn.execute('SELECT * FROM trade_executions LIMIT 0').description]
    return dict(zip(cols, row))


# ── costs ────────────────────────────────────────────────────────────────
def record_costs(conn: sqlite3.Connection, trade_id: str, phase: str, cost_lines,
                 now: Optional[float] = None) -> None:
    """Store a set of cost lines under 'quoted' or 'actual'."""
    if phase not in ('quoted', 'actual'):
        raise LedgerError(f'phase must be quoted or actual, not {phase!r}')
    ts = now if now is not None else time.time()
    conn.executemany(
        'INSERT INTO trade_costs (trade_id, kind, phase, usd, payer, source, '
        'sponsored, detail, created_at) VALUES (?,?,?,?,?,?,?,?,?)',
        [(trade_id, c.kind, phase, str(c.usd), c.payer, c.source,
          1 if c.sponsored else 0, c.detail, ts) for c in cost_lines])
    conn.commit()


def cost_drift(conn: sqlite3.Connection, trade_id: str) -> dict:
    """Quoted against actual, per cost kind.

    Reported per kind rather than as one total because a total that happens
    to match can hide a bridge that came in cheap against gas that came in
    expensive -- and the second of those is the one worth knowing about.
    """
    rows = conn.execute(
        'SELECT kind, phase, SUM(CAST(usd AS REAL)) FROM trade_costs '
        'WHERE trade_id=? GROUP BY kind, phase', (trade_id,)).fetchall()
    out: dict = {}
    for kind, phase, total in rows:
        out.setdefault(kind, {'quoted': 0.0, 'actual': 0.0})[phase] = float(total or 0)
    for kind, v in out.items():
        v['drift'] = round(v['actual'] - v['quoted'], 6)
    return out


# ── reservations ─────────────────────────────────────────────────────────
def held_usd(conn: sqlite3.Connection, user_id: int, chain: str) -> Decimal:
    """What this user has already claimed on this chain and not yet released."""
    row = conn.execute(
        "SELECT COALESCE(SUM(CAST(amount_usd AS REAL)), 0) FROM balance_reservations "
        "WHERE user_id=? AND chain=? AND status='held'", (user_id, chain)).fetchone()
    return _d(row[0] or 0)


def reserve(conn: sqlite3.Connection, *, user_id: int, chain: str, trade_id: str,
            amount_usd, available_usd, now: Optional[float] = None) -> None:
    """Claim `amount_usd` against a balance, atomically.

    BEGIN IMMEDIATE takes the write lock before reading what is already held,
    so two trades cannot both read the same free balance and both decide
    there is room. Without it this is a check-then-act race, which is the
    whole reason the reservation exists.
    """
    amount = _d(amount_usd)
    available = _d(available_usd)
    if amount <= 0:
        raise LedgerError('cannot reserve a non-positive amount')
    ts = now if now is not None else time.time()
    try:
        conn.execute('BEGIN IMMEDIATE')
        already = held_usd(conn, user_id, chain)
        free = available - already
        if amount > free:
            raise InsufficientAvailable(
                f'${amount} exceeds the ${free} still free on {chain} '
                f'(${available} present, ${already} already reserved by another trade)'
            )
        conn.execute(
            'INSERT INTO balance_reservations (user_id, chain, trade_id, amount_usd, '
            "status, created_at) VALUES (?,?,?,?,'held',?)",
            (user_id, chain, trade_id, str(amount), ts))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def settle(conn: sqlite3.Connection, trade_id: str, actual_spend_usd,
           now: Optional[float] = None) -> Decimal:
    """Close a reservation at what was really spent. Returns what is released.

    A trade that came in under its reservation gives the difference straight
    back; a trade that somehow came in over keeps its full claim, because
    releasing money that was actually spent would credit the user twice.
    """
    row = conn.execute(
        "SELECT amount_usd, status FROM balance_reservations WHERE trade_id=?",
        (trade_id,)).fetchone()
    if not row:
        raise LedgerError(f'no reservation for trade {trade_id}')
    if row[1] != 'held':
        raise LedgerError(f'reservation for {trade_id} is already {row[1]}')
    reserved = _d(row[0])
    spent = _d(actual_spend_usd)
    released = reserved - spent if spent < reserved else _d(0)
    conn.execute(
        "UPDATE balance_reservations SET status='settled', amount_usd=?, closed_at=? "
        "WHERE trade_id=?",
        (str(spent if spent < reserved else reserved),
         now if now is not None else time.time(), trade_id))
    conn.commit()
    return released


def release(conn: sqlite3.Connection, trade_id: str, now: Optional[float] = None) -> Decimal:
    """Give back the whole claim -- for a trade that never executed."""
    row = conn.execute(
        "SELECT amount_usd, status FROM balance_reservations WHERE trade_id=?",
        (trade_id,)).fetchone()
    if not row:
        raise LedgerError(f'no reservation for trade {trade_id}')
    if row[1] != 'held':
        raise LedgerError(f'reservation for {trade_id} is already {row[1]}')
    conn.execute(
        "UPDATE balance_reservations SET status='released', closed_at=? WHERE trade_id=?",
        (now if now is not None else time.time(), trade_id))
    conn.commit()
    return _d(row[0])
