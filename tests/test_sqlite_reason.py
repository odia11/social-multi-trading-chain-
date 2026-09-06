"""sqlite3.OperationalError is not one error, and treating it as one sends
people into retry loops that cannot possibly work.

"Database busy — try again in a moment" was shown for EVERY OperationalError.
Only one of them is worth retrying. A read-only volume, a full disk and a
stale schema all told the user to try again, forever, while hiding the one
fact that would have explained it.

These drive the real _sqlite_reason from dashboard.py with real SQLite errors
raised by a real database -- a read-only file, a missing table -- rather than
with hand-written strings."""
import os, re, sqlite3, stat, sys, tempfile

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC  = open(REPO + '/dashboard.py').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

ns = {}
m = re.search(r'^def _sqlite_reason\(e\) -> tuple:.*?\n(?=\S)', SRC, re.M | re.S)
assert m, 'not found'
exec(m.group(0), ns)
reason = ns['_sqlite_reason']

def real_error(fn):
    try:
        fn(); return None
    except sqlite3.OperationalError as e:
        return e

# ── a genuinely read-only database file ──
db = tempfile.mktemp(suffix='.db')
c = sqlite3.connect(db); c.execute('CREATE TABLE t (v TEXT)'); c.commit(); c.close()
os.chmod(db, stat.S_IRUSR)
os.chmod(os.path.dirname(db), stat.S_IRUSR | stat.S_IXUSR)
def _w():
    conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    try: conn.execute("INSERT INTO t VALUES ('x')"); conn.commit()
    finally: conn.close()
e_ro = real_error(_w)
os.chmod(os.path.dirname(db), stat.S_IRWXU)
check('a real read-only database raises OperationalError, not something else',
      e_ro is not None)
msg, code = reason(e_ro)
check('...and is reported as read-only, not as "busy"',
      'read-only' in msg.lower() and 'try again' not in msg.lower())
check('...with a 500, because retrying is pointless — it is not the user\'s problem '
      'to solve by pressing the button again', code == 500)

# ── a real missing table ──
c = sqlite3.connect(db)
e_tab = real_error(lambda: c.execute('INSERT INTO nope VALUES (1)'))
c.close(); os.chmod(db, stat.S_IRWXU); os.unlink(db)
check('a real missing table is recognised as a schema problem',
      e_tab is not None and 'schema' in reason(e_tab)[0].lower())

# ── the one case that IS worth retrying ──
msg, code = reason(sqlite3.OperationalError('database is locked'))
check('a locked database still says to try again — the only case where that advice '
      'is true', 'try again' in msg.lower() and code == 503)
msg, _ = reason(sqlite3.OperationalError('database table is locked: trades'))
check('...and so does the table-level variant', 'try again' in msg.lower())

msg, code = reason(sqlite3.OperationalError('database or disk is full'))
check('a full disk says the storage is full, not that the database is busy',
      'full' in msg.lower() and 'busy' not in msg.lower() and code == 500)
msg, _ = reason(sqlite3.OperationalError('disk I/O error'))
check('a disk I/O error is a storage problem too', 'storage' in msg.lower())

# ── anything unmapped ──
msg, code = reason(sqlite3.OperationalError('some brand new sqlite message'))
check('an error nobody mapped shows the real SQLite text instead of inventing a '
      'cause — a wrong explanation is worse than an unfamiliar one',
      'some brand new sqlite message' in msg)
check('...and is not passed off as busy', 'busy' not in msg.lower())
check('a very long message is trimmed rather than filling the screen',
      len(reason(sqlite3.OperationalError('x' * 500))[0]) < 130)

# ── the call route uses it ──
call = re.search(r'def api_make_call\(\):.*?\n(?=@app\.route)', SRC, re.S).group(0)
check('the call route routes its OperationalError through this instead of assuming',
      '_sqlite_reason(e)' in call and 'Database busy' not in call)
check('...and logs the exception type and text, so the log is not guesswork either',
      "type(e).__name__" in call)

# ── the startup self-test ──
st = re.search(r'def _db_write_selftest\(\):.*?\n(?=\S)', SRC, re.S).group(0)
check('startup actually WRITES to the database rather than only opening it — '
      'reads kept working while every write failed, which is what hid this',
      'INSERT INTO _write_selftest' in st and 'commit()' in st)
check('...and cleans up after itself', 'DELETE FROM _write_selftest' in st)
check('it reports free space, so a filling volume is visible before it breaks writes',
      'disk_usage' in st and 'MB free' in st)
check('it warns while there is still room to act, not only once writes fail',
      'free_mb < 50' in st)
check('a failure prints what actually went wrong and what it means for the app',
      'NOT WRITABLE' in st and 'every write' in st)
check('the self-test can never stop the app from starting',
      'except Exception as e:' in st
      and not re.search(r'^\s*raise\b', st, re.M))   # the word in the docstring is not a statement
check('it runs at startup', re.search(r'^_db_write_selftest\(\)', SRC, re.M))

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
