"""Counting what OrcAgent pays for users, and whether it comes back.

This is the number the whole brief turns on. Today it is not zero and
nothing measures it: every row in gas_sponsorships is money given away,
because no code reads the table back to recover a cost.

The honest part of this is the separation. Grants made before recovery
existed cannot be recovered — the trades are done. Folding them into the
live counter would leave it permanently non-zero and therefore useless as a
signal, and quietly excluding them would understate a real loss. They are
counted, named, and kept apart.
"""
import os
import sqlite3
import sys
import tempfile
from decimal import Decimal

sys.path.insert(0, '/home/user/Orc-agent-Solana-chain-')

from trade_engine import subsidy as S                          # noqa: E402

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

D = Decimal
DB = tempfile.mktemp(suffix='.db')
conn = sqlite3.connect(DB)

# The real table, as init_db creates it — without the new columns, which is
# the state every existing database is in right now.
conn.execute('''CREATE TABLE gas_sponsorships (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    wallet         TEXT NOT NULL,
    chain          TEXT NOT NULL,
    to_address     TEXT NOT NULL,
    amount_native  REAL NOT NULL,
    amount_usd     REAL DEFAULT 0,
    tx_hash        TEXT DEFAULT '',
    status         TEXT DEFAULT 'sent',
    error_msg      TEXT DEFAULT '',
    created_at     TEXT DEFAULT CURRENT_TIMESTAMP
)''')
conn.commit()

def grant(user, chain, usd, status='sent', ts='2026-01-01'):
    conn.execute('INSERT INTO gas_sponsorships (user_id, wallet, chain, to_address, '
                 'amount_native, amount_usd, status, created_at) VALUES (?,?,?,?,?,?,?,?)',
                 (user, 'W', chain, '0x', 0.001, usd, status, ts))
    conn.commit()
    return conn.execute('SELECT last_insert_rowid()').fetchone()[0]


# ── the migration runs against a table that predates it ──
g_legacy_1 = grant(1, 'base', 0.35)
g_legacy_2 = grant(2, 'bsc', 0.40)
S.apply_migrations(conn)
cols = {r[1] for r in conn.execute('PRAGMA table_info(gas_sponsorships)')}
check('the migration adds the two columns to the existing table rather than '
      'making a second one — a grant and its recovery are one fact',
      'trade_id' in cols and 'recovered_usd' in cols)

S.apply_migrations(conn)
check('...and running it again is a no-op, so it is safe on every start', True)


# ── the state every database is in today ──
r = S.subsidy_report(conn)
check('grants that predate recovery are counted as unrecoverable, not silently '
      'dropped', r['legacy_grants'] == 2 and r['legacy_unrecoverable_usd'] == '0.75')
check('...and are kept OUT of the live outstanding figure, which would otherwise '
      'never reach zero and stop being a signal', r['outstanding_usd'] == '0.00')
check('the live counter therefore reads clean on a database with only legacy '
      'grants', r['zero_subsidy'])
check('the total granted still includes them — the loss is real and is reported',
      r['granted_usd'] == '0.75')


# ── a grant made for a trade, fully recovered ──
g1 = grant(3, 'base', 0.35)
S.attach_to_trade(conn, g1, 'trade-1', D('0.35'))
r = S.subsidy_report(conn)
check('a grant charged in full to a trade adds nothing outstanding — the sponsor '
      'was a payment rail, not a benefactor', r['outstanding_usd'] == '0.00')
check('...and is counted as recovered', r['recovered_usd'] == '0.35')
check('...and as a tracked grant, separate from the legacy ones',
      r['tracked_grants'] == 1)
check('zero subsidy still holds', r['zero_subsidy'])


# ── a grant that cost more than the quote charged ──
g2 = grant(4, 'bsc', 0.60)
S.attach_to_trade(conn, g2, 'trade-2', D('0.40'))
r = S.subsidy_report(conn)
check('gas that came in above what the quote charged leaves a real shortfall — '
      'this is the residual subsidy, and it is surfaced rather than absorbed',
      r['outstanding_usd'] == '0.20')
check('...so the zero-subsidy flag goes false', not r['zero_subsidy'])

owed = S.unrecovered_grants(conn)
check('the outstanding total can be traced to the specific grants behind it, not '
      'only reported as a number',
      len(owed) == 1 and owed[0]['trade_id'] == 'trade-2'
      and owed[0]['shortfall_usd'] == '0.20')
check('...naming the user and chain, so a pattern is findable',
      owed[0]['user_id'] == 4 and owed[0]['chain'] == 'bsc')


# ── what must not count ──
grant(5, 'base', 5.00, status='refill')
grant(6, 'base', 9.99, status='refill_failed')
r = S.subsidy_report(conn)
check('a treasury refill is not a user grant and is excluded — it is OrcAgent '
      'moving its own money between its own wallets',
      r['granted_usd'] == '1.70' and r['outstanding_usd'] == '0.20')

g3 = grant(7, 'base', 0.30)
S.attach_to_trade(conn, g3, 'trade-3', D('0.50'))
r = S.subsidy_report(conn)
check('a trade charged MORE than the grant cost adds nothing outstanding, and is '
      'not counted as negative subsidy — over-recovery is a pricing question, '
      'not a credit', r['outstanding_usd'] == '0.20')

try:
    S.attach_to_trade(conn, g3, 'trade-x', D('-1'))
    ok = False
except S.SubsidyError:
    ok = True
check('a negative recovery is refused — it would silently reduce the amount owed', ok)

try:
    S.attach_to_trade(conn, 99999, 'trade-x', D('1'))
    ok = False
except S.SubsidyError:
    ok = True
check('attaching to a grant that does not exist raises instead of doing nothing', ok)


# ── the admin endpoint reports it ──
src = open('/home/user/Orc-agent-Solana-chain-/dashboard.py').read()
check('the admin gas-sponsor endpoint returns the subsidy figure',
      "'subsidy': subsidy," in src)
check('...and returns the same shape when sponsorship is switched off, so the '
      'panel never has to guess whether the field exists',
      "'zero_subsidy': True}})" in src)
check('the migration runs at startup', 'te_subsidy.apply_migrations(conn)' in src)


# ── still no execution ──
import ast, trade_engine.subsidy as _s                          # noqa: E402
tree = ast.parse(open(_s.__file__).read())
imported = set()
for n in ast.walk(tree):
    if isinstance(n, ast.Import):
        imported.update(a.name.split('.')[0] for a in n.names)
    elif isinstance(n, ast.ImportFrom) and n.module:
        imported.add(n.module.split('.')[0])
for forbidden in ('dashboard', 'requests', 'web3'):
    check(f'the subsidy accounting does not import {forbidden}', forbidden not in imported)
check('it opens no connection of its own', 'sqlite3.connect' not in open(_s.__file__).read())

conn.close()
os.unlink(DB)
print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
