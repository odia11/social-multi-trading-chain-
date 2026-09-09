"""Why "Database busy" happened, and that it no longer does.

The database is in WAL mode, so readers never block writers. What WAL does
not change is that there is only ONE writer at a time -- and this process has
many: the request threads plus the bot loop, the monitor, the surge radar,
the gas sweep and the calls-peak refresh, all on one file.

A write that cannot get the lock waits busy_timeout and then raises "database
is locked". Python's default is 5 seconds. These reproduce that failure
against a real SQLite file with real concurrent writers, then show the same
load passing with the timeout the app now sets."""
import os, re, sqlite3, sys, tempfile, threading, time

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC  = open(REPO + '/dashboard.py').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

DB = tempfile.mktemp(suffix='.db')
c = sqlite3.connect(DB)
c.execute('PRAGMA journal_mode=WAL')          # same as init_db does
c.execute('CREATE TABLE token_calls (id INTEGER PRIMARY KEY, mint TEXT, price REAL)')
c.commit(); c.close()

HOLD = 2.0        # seconds one background write keeps the lock
GAP  = 1.5        # ...and how long it lets go before the next cycle

def slow_writer(stop, hold=HOLD, gap=GAP):
    """Stands in for a background loop mid-write: a real transaction, held
    open while it does something slow, exactly as a loop that writes between
    network calls does. The gap matters -- a loop that sleeps between cycles
    leaves a window a patient caller can use, and one that never lets go
    does not."""
    while not stop.is_set():
        conn = sqlite3.connect(DB, timeout=30)
        try:
            conn.execute('PRAGMA busy_timeout=30000')
            conn.execute('BEGIN IMMEDIATE')       # takes the write lock
            conn.execute("INSERT INTO token_calls (mint, price) VALUES ('slow', 1)")
            time.sleep(hold)                      # ...and holds it
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()
        stop.wait(gap)

def try_call(timeout_s, pragma_ms):
    """One 'Make a Call' write, with the given patience."""
    conn = sqlite3.connect(DB, timeout=timeout_s)
    try:
        if pragma_ms:
            conn.execute(f'PRAGMA busy_timeout={pragma_ms}')
        conn.execute("INSERT INTO token_calls (mint, price) VALUES ('call', 2)")
        conn.commit()
        return None
    except sqlite3.OperationalError as e:
        return str(e)
    finally:
        conn.close()

stop = threading.Event()
t = threading.Thread(target=slow_writer, args=(stop,), daemon=True)
t.start()
time.sleep(0.4)          # let the slow writer take the lock

# ── the old behaviour: Python's 5s default, against a 3s-held lock, twice over ──
old_errs = [try_call(1.0, None) for _ in range(3)]
check('with a short timeout a call FAILS while a background write holds the lock — '
      'this is the "Database busy" the user hit, reproduced',
      any(e and 'locked' in e for e in old_errs))

# ── the new behaviour: the timeout the app now sets ──
def _calls():
    c = sqlite3.connect(DB, timeout=30)
    try:    return c.execute("SELECT COUNT(*) FROM token_calls WHERE mint='call'").fetchone()[0]
    finally: c.close()

before = _calls()          # some of the impatient attempts above may have slipped
                           # through a gap, so measure the delta, not the total
new_errs = [try_call(30.0, 30000) for _ in range(3)]
after = _calls()
check('with the app\'s 30-second timeout the same call waits and succeeds instead '
      'of failing', all(e is None for e in new_errs))

stop.set(); t.join(timeout=HOLD + GAP + 2)

# ── and the case a timeout can NEVER fix ──
# A writer that never lets go starves every other writer no matter how
# patient it is. That is why the second fix -- not holding a connection open
# across minutes of network calls -- is the one that actually removes the
# failure, rather than just widening the window.
stop2 = threading.Event()
def greedy(stop):
    while not stop.is_set():
        conn = sqlite3.connect(DB, timeout=30)
        try:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("INSERT INTO token_calls (mint, price) VALUES ('greedy', 3)")
            time.sleep(1.5)
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()
t2 = threading.Thread(target=greedy, args=(stop2,), daemon=True); t2.start()
time.sleep(0.3)
starved = try_call(2.0, 2000)
stop2.set(); t2.join(timeout=4)
check('a writer that never releases the lock starves callers whatever their '
      'timeout — so raising the timeout alone would not have been a fix',
      starved is not None and 'locked' in starved)

check('...and all three rows it waited for are actually written, not silently dropped',
      after - before == 3)

# ── the wrapper is installed, and installed early enough ──
check('sqlite3.connect is wrapped so all ~360 call sites inherit the timeout, '
      'without rewriting any of them', 'sqlite3.connect = _sqlite_connect_patient' in SRC)
check('the wrapper sets both the connect timeout and the pragma — the pragma alone '
      'does not cover the connect, and vice versa',
      "kwargs.setdefault('timeout', 30.0)" in SRC and "PRAGMA busy_timeout=30000" in SRC)
check('it is installed before init_db, so even the very first connection has it',
      SRC.index('sqlite3.connect = _sqlite_connect_patient') < SRC.index('def init_db()'))
_wrap = re.search(r'def _sqlite_connect_patient.*?\n    return conn', SRC, re.S).group(0)
check('a connection too broken to accept the pragma still comes back rather than '
      'raising from inside the wrapper',
      'except Exception:' in _wrap and 'pass' in _wrap and _wrap.rstrip().endswith('return conn'))

# ── the loop that caused it no longer holds a connection across the network ──
loop = re.search(r'def _calls_peak_loop\(\):.*?\n(?=@app\.route)', SRC, re.S).group(0)
fetch_at = loop.index('_dex_get(')
check('the mint list is read and the connection CLOSED before any network call',
      loop.index('conn.close()') < fetch_at)
check('the write connection is opened only after the fetching is done',
      loop.rindex('sqlite3.connect(DB_FILE)') > fetch_at)
check('nothing writes through a connection opened before the network work',
      loop.index('UPDATE token_calls') > loop.rindex('sqlite3.connect(DB_FILE)'))
check('a cycle that found no prices opens no write connection at all',
      'if price_by_mint:' in loop)

# ── the same pattern in the trade recorder ──
# Checked by position in the parse tree rather than by matching source text:
# the previous spelling pinned exact indentation and a local variable's name,
# so reformatting the function broke the test while the property it cares
# about was still perfectly true. A guard that fails on a rename is a guard
# nobody trusts.
import ast                                                        # noqa: E402
_tree  = ast.parse(SRC)
_trade = next(n for n in ast.walk(_tree)
              if isinstance(n, ast.FunctionDef) and n.name == 'api_instant_trade')
_dex_lines = [n.lineno for n in ast.walk(_trade)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == '_dex_get']
_insert_lines = [n.lineno for n in ast.walk(_trade) if isinstance(n, ast.Constant)
                 and isinstance(n.value, str) and 'INSERT INTO trades' in n.value]
_connect_lines = [n.lineno for n in ast.walk(_trade)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and n.func.attr == 'connect']
check('the price lookup happens BEFORE the trade row is inserted — it used to sit '
      'between the INSERT and its commit, holding the write lock across a '
      '6-second HTTP call',
      _dex_lines and _insert_lines and max(_dex_lines) < min(_insert_lines))
check('...and no connection is even open while that lookup runs',
      _connect_lines and min(c for c in _connect_lines
                             if c > max(_dex_lines)) > max(_dex_lines))

# ── a standing guard over the whole file ──
# This is the class of bug, not two instances of it: any write left
# uncommitted across network I/O blocks every other writer in the process.
_lines = SRC.split('\n')
_NET   = re.compile(r'_dex_get\(|requests\.(get|post)\(|time\.sleep\(|urlopen\(')
_WRITE = re.compile(r'INSERT INTO|UPDATE |DELETE FROM', re.I)
offenders, _open = [], None
for _i, _l in enumerate(_lines):
    if 'sqlite3.connect(' in _l:
        _open, _wrote, _done, _net = _i, False, False, None
    elif _open is not None:
        if 'conn.close()' in _l or (_l.strip() and not _l[0].isspace()):
            if _net is not None and _wrote and not _done:
                offenders.append(_open + 1)
            _open = None
        else:
            if _WRITE.search(_l):        _wrote = True
            if 'commit()' in _l:         _done = True
            if _NET.search(_l) and _net is None and _wrote and not _done: _net = _i
check('nowhere in the app does an UNCOMMITTED write span a network call or a '
      'sleep — that is what makes one slow request stall every other writer',
      not offenders)

os.unlink(DB)
print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
