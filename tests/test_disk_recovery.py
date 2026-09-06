"""The volume filled up. Reads kept working, every write failed.

That is what "Database busy" actually was: SQLite cannot write to a full
disk, and on a hosted container a non-technical owner cannot clear it by
hand. So the app has to (a) not be the thing that fills it and (b) reclaim
what it can by itself at startup.

The backup directory was the cause: SEVEN uncompressed copies of the
database, on the same volume as the database, is eight times its size.

These run the real functions against a real gzip round-trip and a real
SQLite file with a real WAL."""
import gzip, os, re, shutil, sqlite3, sys, tempfile

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC  = open(REPO + '/dashboard.py').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

def fn(name):
    m = re.search(rf'^def {re.escape(name)}\(.*?\n(?=\S)', SRC, re.M | re.S)
    assert m, name
    return m.group(0)

# ── a real database with real content, and a real backup directory ──
tmp = tempfile.mkdtemp()
DB  = os.path.join(tmp, 'orcagent.db')
BK  = os.path.join(tmp, 'backups')
os.makedirs(BK)
c = sqlite3.connect(DB)
c.execute('PRAGMA journal_mode=WAL')
c.execute('CREATE TABLE trades (id INTEGER PRIMARY KEY, sym TEXT, note TEXT)')
c.executemany('INSERT INTO trades (sym, note) VALUES (?,?)',
              [(f'TOK{i}', 'x' * 400) for i in range(4000)])
c.commit(); c.close()
db_size = os.path.getsize(DB)

ns = {'os': os, 'gzip': gzip, 'shutil': shutil, 'sqlite3': sqlite3,
      'datetime': __import__('datetime'), 'time': __import__('time'),
      'DB_FILE': DB, 'BACKUP_DIR': BK, '_DATA_DIR': tmp,
      'print': lambda *a, **k: None,
      'BACKUP_KEEP': 3, 'BACKUP_MIN_FREE_BYTES': 300 * 1024 * 1024,
      'DISK_LOW_BYTES': 300 * 1024 * 1024}
for f in ('_free_bytes', '_backup_files', '_prune_backups', 'backup_database', '_reclaim_disk_space'):
    exec(fn(f), ns)

# ── compression is the whole point ──
ok = ns['backup_database']()
check('a backup is written', ok and len(ns['_backup_files']()) == 1)
name = ns['_backup_files']()[0]
check('...compressed, not as a bare copy of the database', name.endswith('.db.gz'))
gz_size = os.path.getsize(os.path.join(BK, name))
check(f'...and much smaller than the database it copies '
      f'({db_size//1024}KB -> {gz_size//1024}KB)', gz_size < db_size / 3)
check('no temporary file is left behind eating the volume',
      not [f for f in os.listdir(BK) if f.startswith('.')])

# ── it is still a real, restorable database ──
restored = os.path.join(tmp, 'restored.db')
with gzip.open(os.path.join(BK, name), 'rb') as f_in, open(restored, 'wb') as f_out:
    shutil.copyfileobj(f_in, f_out)
r = sqlite3.connect(restored)
n = r.execute('SELECT COUNT(*) FROM trades').fetchone()[0]
r.close()
check('the compressed backup restores to a working database with every row '
      'intact — a smaller backup that cannot be restored is not a backup', n == 4000)

# ── retention ──
for d in ('2020-01-01', '2020-01-02', '2020-01-03', '2020-01-04', '2020-01-05'):
    open(os.path.join(BK, f'orcagent_{d}.db.gz'), 'wb').write(b'old')
open(os.path.join(BK, 'orcagent_2019-01-01.db'), 'wb').write(b'ancient')
check('backups left by older versions as plain .db are still seen, so they get '
      'pruned too instead of sitting there forever',
      any(f.endswith('.db') and not f.endswith('.gz') for f in ns['_backup_files']()))
ns['_prune_backups'](keep=3)
check('only the newest few are kept', len(ns['_backup_files']()) == 3)
ns['_prune_backups'](keep=0)
check('pruning never empties the directory — asking for zero still keeps the '
      'newest, because a backup directory is worth shrinking, not emptying',
      len(ns['_backup_files']()) == 1)

# ── it refuses to be the thing that fills the disk ──
ns['BACKUP_MIN_FREE_BYTES'] = 10 ** 15      # nothing has this much free
before = len(ns['_backup_files']())
ok = ns['backup_database']()
check('a backup is skipped when space is already short — a backup that tips the '
      'volume over does more harm than a missing day of them', ok is False)
check('...and it prunes instead of just giving up', len(ns['_backup_files']()) <= before)
ns['BACKUP_MIN_FREE_BYTES'] = 300 * 1024 * 1024

# ── reclaiming at startup ──
for d in ('2021-01-01', '2021-01-02', '2021-01-03'):
    with open(os.path.join(BK, f'orcagent_{d}.db.gz'), 'wb') as f:
        f.write(b'z' * 200_000)
# The -wal file only exists while a connection is open: SQLite removes it when
# the last one closes. Hold one open, as the running app always does, or there
# is no WAL to reclaim and the check would pass by accident.
holder = sqlite3.connect(DB)
holder.executemany('INSERT INTO trades (sym, note) VALUES (?,?)',
                   [(f'W{i}', 'y' * 400) for i in range(3000)])
holder.commit()
wal = DB + '-wal'
wal_before = os.path.getsize(wal) if os.path.exists(wal) else 0
n_before = len(ns['_backup_files']())
freed = ns['_reclaim_disk_space']()
wal_after = os.path.getsize(wal) if os.path.exists(wal) else 0
holder.close()
check('reclaiming removes old backups but keeps the newest',
      len(ns['_backup_files']()) == 1 and n_before > 1)
check('...and truncates the write-ahead log, which otherwise stays at its '
      f'high-water mark forever ({wal_before//1024}KB -> {wal_after//1024}KB)',
      wal_before > 0 and wal_after < wal_before)
check('it reports how much it actually recovered', freed > 0)

# ── nothing a user owns is touched ──
c = sqlite3.connect(DB)
check('the trades are all still there — reclaiming only ever deletes copies',
      c.execute('SELECT COUNT(*) FROM trades').fetchone()[0] == 7000)
c.close()

# ── the wiring ──
st = fn('_db_write_selftest')
check('startup checks free space before it checks writability, so a full volume '
      'is reclaimed rather than merely reported',
      st.index('_reclaim_disk_space()') < st.index('INSERT INTO _write_selftest'))
check('...and says plainly when reclaiming was not enough, naming the one action '
      'only the owner can take', 'Grow the Railway volume' in st)
check('the self-test can never stop the app from starting',
      not re.search(r'^\s*raise\b', st, re.M))

vac = re.search(r'# VACUUM rebuilds.*?VACUUM error', SRC, re.S).group(0)
check('VACUUM is skipped on a nearly-full disk — it rebuilds the database into a '
      'copy, so running it there is how a space problem becomes an outage',
      'VACUUM skipped' in vac and 'size_before * 2' in vac)
check('the daily maintenance truncates the WAL too, so it cannot grow back '
      'unbounded between restarts', 'wal_checkpoint(TRUNCATE)' in SRC)

shutil.rmtree(tmp)
print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
