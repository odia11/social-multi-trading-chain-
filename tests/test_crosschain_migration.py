"""The new table has to appear on a database that already exists.

A migration that only works on a fresh database is not a migration. Every
deployment this ships to has months of trades in it, so the check that
matters is: open an OLD database -- one with the engine's other tables but no
trade_crosschain -- run the schema, and see the table arrive with the data
still there.
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trade_engine import ledger as L                # noqa: E402

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


DB = os.path.join(tempfile.mkdtemp(), 'old.db')
conn = sqlite3.connect(DB)

# ── an "old" database: every engine table except the new one ──
for ddl in L.SCHEMA:
    if 'trade_crosschain' in ddl:
        continue
    conn.execute(ddl)
conn.execute(
    "INSERT INTO trade_executions (trade_id, idempotency_key, quote_id, user_id, "
    "wallet, mode, state, same_chain, max_spend_usd, created_at, updated_at) "
    "VALUES ('old-trade','old-key','old-quote',1,'W','manual','COMPLETED',1,'50',1,1)")
conn.commit()

tables_before = {r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'")}
check('the starting point really is missing the new table, so this is a '
      'migration and not a fresh create wearing one as a costume',
      'trade_crosschain' not in tables_before
      and 'trade_executions' in tables_before)

# ── the migration ──
L.ensure_schema(conn)

tables_after = {r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'")}
check('trade_crosschain is created on an existing database',
      'trade_crosschain' in tables_after)
check('...and the trades that were already there survived it',
      conn.execute("SELECT state FROM trade_executions WHERE trade_id='old-trade'"
                   ).fetchone()[0] == 'COMPLETED')

# ── running it twice must be a no-op, because startup runs it every boot ──
L.ensure_schema(conn)
L.ensure_schema(conn)
check('running the schema again changes nothing and raises nothing — it runs '
      'on every single start, so "safe to re-run" is not optional',
      conn.execute('SELECT COUNT(*) FROM trade_executions').fetchone()[0] == 1)

# ── the columns a recovery actually needs ──
cols = {r[1] for r in conn.execute('PRAGMA table_info(trade_crosschain)')}
needed = {'trade_id', 'quote_id', 'user_id', 'provider', 'route_id',
          'source_chain', 'destination_chain', 'source_token',
          'destination_token', 'source_amount_raw', 'quoted_out_raw',
          'minimum_out_raw', 'actual_out_raw', 'provider_status',
          'source_tx_hash', 'bridge_tx_hash', 'destination_tx_hash',
          'swap_tx_hash', 'estimated_fees_json', 'actual_fees_json',
          'estimated_seconds', 'failure_reason', 'poll_attempts',
          'source_sent_at', 'created_at', 'updated_at'}
missing = needed - cols
check('every identifier a restart needs to find, identify and finish a trade '
      f'is a column: {sorted(missing) or "none missing"}', not missing)

# ── trade_id is the PRIMARY KEY, which is the duplicate-bridge guard ──
pk = [r[1] for r in conn.execute('PRAGMA table_info(trade_crosschain)') if r[5]]
check('trade_id is the PRIMARY KEY — that is what makes a second bridge for '
      'one trade impossible, in the database, rather than a check two '
      'concurrent callers could both pass', pk == ['trade_id'])

conn.execute("INSERT INTO trade_crosschain (trade_id, quote_id, user_id, provider, "
             "source_chain, destination_chain, source_token, destination_token, "
             "source_amount_raw, created_at, updated_at) "
             "VALUES ('t1','q1',1,'0x','base','solana','a','b','1',1,1)")
conn.commit()
try:
    conn.execute("INSERT INTO trade_crosschain (trade_id, quote_id, user_id, provider, "
                 "source_chain, destination_chain, source_token, destination_token, "
                 "source_amount_raw, created_at, updated_at) "
                 "VALUES ('t1','q1',1,'0x','base','solana','a','b','1',1,1)")
    check('...and the database enforces it', False)
except sqlite3.IntegrityError:
    check('...and the database enforces it', True)

conn.close()

# ── the states the resume worker looks for must all be real states ──
check('every resumable state is a state the machine actually has, so the '
      'recovery query can never silently match nothing',
      L.RESUMABLE <= set(L.TRANSITIONS))
check('...and none of them is terminal, which would mean the worker kept '
      'picking up finished trades forever', not (L.RESUMABLE & L.TERMINAL))

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
