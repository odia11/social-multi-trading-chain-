"""Turning gas sponsorship from a gift into a loan, and counting what is owed.

WHAT THE SPONSOR ACTUALLY IS
A wallet with no native token cannot broadcast anything, so the sponsor
wallet sends it some. That is a payment rail. It becomes a subsidy only when
nobody is charged for it -- which is what happens today: every grant is
written to gas_sponsorships and no code anywhere reads it back to recover
the cost. The whole of that table is, at present, money OrcAgent gave away.

WHAT THIS ADDS
Two columns and an accounting. A grant made for a trade carries that trade's
id and the amount the user's budget was charged for it. A grant with no
trade, or with less recovered than granted, is a subsidy -- and the report
below says how much, which is the number the brief wants at zero.

WHY IT COUNTS RATHER THAN CORRECTS
Historical grants cannot be recovered: the trades are done and the users are
gone. Presenting them as anything other than a loss would be a lie, so they
are counted separately as legacy rather than quietly excluded from the
total. What the counter measures going forward is whether NEW grants are
recovered.

Takes a connection. No network, no app, no execution.
"""
from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Optional

# Added to the existing gas_sponsorships table rather than duplicating it:
# the grant and its recovery are one fact, and splitting them across two
# tables is how they drift apart.
MIGRATIONS = [
    "ALTER TABLE gas_sponsorships ADD COLUMN trade_id TEXT DEFAULT ''",
    "ALTER TABLE gas_sponsorships ADD COLUMN recovered_usd REAL DEFAULT 0",
]


class SubsidyError(Exception):
    pass


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Add the columns if they are missing. Safe on every start."""
    for stmt in MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            if 'duplicate column' not in str(e).lower():
                raise
    conn.commit()


CENT = Decimal('0.01')


def _d(v) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v or 0))


def _usd(v: Decimal) -> str:
    """A money figure, always to the cent.

    Decimal('0.6') - Decimal('0.4') is Decimal('0.2'), and "$0.2" is not how
    an amount of money is written. Quantised on the way out so every figure
    in the report reads as currency.
    """
    return str(v.quantize(CENT))


def attach_to_trade(conn: sqlite3.Connection, sponsorship_id: int, trade_id: str,
                    recovered_usd) -> None:
    """Record that a grant was charged to a trade's budget.

    `recovered_usd` is what the QUOTE charged the user for gas, not what the
    grant cost -- those differ when gas moves between quote and broadcast,
    and the difference is exactly the residual subsidy this is here to
    surface rather than hide.
    """
    amount = _d(recovered_usd)
    if amount < 0:
        raise SubsidyError('recovered amount cannot be negative')
    cur = conn.execute(
        'UPDATE gas_sponsorships SET trade_id=?, recovered_usd=? WHERE id=?',
        (trade_id, float(amount), int(sponsorship_id)))
    if cur.rowcount == 0:
        raise SubsidyError(f'no sponsorship {sponsorship_id}')
    conn.commit()


def subsidy_report(conn: sqlite3.Connection, since_ts: Optional[str] = None) -> dict:
    """What OrcAgent has paid out and how much of it came back.

    `outstanding_usd` is the number that has to reach zero. It counts only
    grants that could have been recovered -- ones made for a trade -- because
    a legacy grant from before recovery existed is a historical loss, not a
    live leak, and mixing the two would make the live number permanently
    non-zero and therefore useless as a signal.
    """
    where = 'WHERE 1=1'
    args: list = []
    if since_ts:
        where += ' AND created_at >= ?'
        args.append(since_ts)

    rows = conn.execute(
        f"SELECT COALESCE(trade_id, ''), COALESCE(amount_usd, 0), "
        f"COALESCE(recovered_usd, 0), status FROM gas_sponsorships {where}",
        args).fetchall()

    granted = _d(0)
    recovered = _d(0)
    outstanding = _d(0)
    legacy = _d(0)
    legacy_count = 0
    tracked_count = 0

    for trade_id, amount_usd, rec_usd, status in rows:
        if status not in ('sent',):
            continue          # refills and failures are not user grants
        amount = _d(amount_usd)
        granted += amount
        if not trade_id:
            legacy += amount
            legacy_count += 1
            continue
        tracked_count += 1
        rec = _d(rec_usd)
        recovered += rec
        if rec < amount:
            outstanding += (amount - rec)

    return {
        'granted_usd': _usd(granted),
        'recovered_usd': _usd(recovered),
        # The live figure. Target: 0.
        'outstanding_usd': _usd(outstanding),
        'tracked_grants': tracked_count,
        # Kept separate and named, because presenting an unrecoverable
        # historical loss as part of a live counter makes the counter useless.
        'legacy_unrecoverable_usd': _usd(legacy),
        'legacy_grants': legacy_count,
        'zero_subsidy': outstanding == _d(0),
    }


def unrecovered_grants(conn: sqlite3.Connection, limit: int = 50) -> list:
    """The specific grants still owed, newest first — so an outstanding
    figure can be traced to the trades that produced it rather than only
    reported as a total."""
    rows = conn.execute(
        "SELECT id, user_id, chain, amount_usd, recovered_usd, trade_id, created_at "
        "FROM gas_sponsorships WHERE status='sent' AND trade_id != '' "
        "AND COALESCE(recovered_usd,0) < COALESCE(amount_usd,0) "
        "ORDER BY created_at DESC LIMIT ?", (int(limit),)).fetchall()
    return [
        {'id': r[0], 'user_id': r[1], 'chain': r[2],
         'granted_usd': _usd(_d(r[3])), 'recovered_usd': _usd(_d(r[4])),
         'shortfall_usd': _usd(_d(r[3]) - _d(r[4])),
         'trade_id': r[5], 'created_at': r[6]}
        for r in rows
    ]
