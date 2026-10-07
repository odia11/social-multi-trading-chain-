"""The long-running app process stays lean.

The VM sat at ~22 of 24 GB. These made the app heavier than it needs to be,
most of them growing for as long as its one process lived:

- glibc's default of 8 malloc arenas per core: with dozens of threads, freed
  memory sat parked in up to 32 arenas (332 MB vs 161 MB after 8,000 requests);
- per-token / per-user caches that honoured a TTL on read but never removed
  an expired entry (every mint the scanner checked, every wallet that logged in);
- every request was logged twice, by nginx and again through journald;
- /api/top-trades-week re-scanned a trader's whole week for each of their
  trades, keeping a request thread busy for over a minute on a busy bot.
"""
import datetime, os, sqlite3, sys, tempfile, threading, time
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0'})

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()

unit = read('deploy', 'orcagent.service')
check('the service limits glibc to two malloc arenas',
      '\nEnvironment=MALLOC_ARENA_MAX=2\n' in unit)
check('gunicorn does not log every request a second time (nginx already does)',
      '--access-logfile' not in unit and '--error-logfile -' in unit)
check('...and still runs exactly one worker',
      '--workers 1 ' in unit and unit.count('--workers') == 1)

import app_entry  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
import memory_hygiene as mh  # noqa: E402

check('app_entry installs the memory janitor',
      getattr(app, '_orca_memory_hygiene_installed', False))
check('...as one background thread',
      sum(t.name == 'orca-memory-hygiene' for t in threading.enumerate()) == 1)

# Every cache the janitor knows about still exists under that name, so a
# rename in dashboard.py cannot silently turn it into a no-op.
names_ok = all(isinstance(getattr(d, n, None), dict) and
               (lk is None or hasattr(getattr(d, lk, None), 'acquire'))
               for n, _, _, lk in mh._TTL_CACHES)
names_ok = names_ok and all(isinstance(getattr(d, n, None), dict) for n, _ in mh._CAPPED)
names_ok = names_ok and all(hasattr(d, n) for n in
                            ('_exit_td_cache', '_exit_td_at', '_exit_td_lock', '_exit_td_inflight'))
check('every cache the janitor prunes exists in dashboard.py with its lock', names_ok)

now = time.time()
old, fresh = now - 7200, now - 1
d._scanner_safety_cache.update({('solana', 'oldmint', False): (old, {'safe': True}),
                                ('solana', 'newmint', False): (fresh, {'safe': True})})
d._realizable_cache.update({('oldmint', '1'): (old, 0.1), ('newmint', '1'): (fresh, 0.2)})
d._AI_TRADE_GATE_CACHE.update({'oldmint': {'decision': {}, 'ts': old},
                               'newmint': {'decision': {}, 'ts': fresh}})
d._guardian_settings_cache.update({101: (old, {}), 102: (fresh, {})})
d._wallet_ips.update({'oldwallet': [('1.1.1.1', old - 100), ('2.2.2.2', old)],
                      'newwallet': [('1.1.1.1', old), ('2.2.2.2', fresh)]})
d._exit_td_cache.update({'oldmint': {'p': 1}, 'newmint': {'p': 2}, 'busymint': {'p': 3},
                         'orphanmint': {'p': 4}})
d._exit_td_at.update({'oldmint': old, 'newmint': fresh, 'busymint': old})
d._exit_td_inflight.add('busymint')
removed = mh.prune(d, now)
check('expired entries are removed from every cache',
      ('solana', 'oldmint', False) not in d._scanner_safety_cache
      and ('oldmint', '1') not in d._realizable_cache
      and 'oldmint' not in d._AI_TRADE_GATE_CACHE
      and 101 not in d._guardian_settings_cache
      and 'oldwallet' not in d._wallet_ips
      and 'oldmint' not in d._exit_td_cache and 'oldmint' not in d._exit_td_at
      and 'orphanmint' not in d._exit_td_cache)
check('fresh entries stay, so no read sees a different answer',
      d._scanner_safety_cache[('solana', 'newmint', False)][1] == {'safe': True}
      and d._realizable_cache[('newmint', '1')][1] == 0.2
      and 'newmint' in d._AI_TRADE_GATE_CACHE and 102 in d._guardian_settings_cache
      and len(d._wallet_ips['newwallet']) == 2
      and d._exit_td_cache['newmint'] == {'p': 2})
check('a token whose data is being refreshed right now is left alone',
      d._exit_td_cache.get('busymint') == {'p': 3} and 'busymint' in d._exit_td_at)
check('the pass reports what it removed', removed == 7)
d._exit_td_inflight.discard('busymint')

# An entry refreshed while the pass runs is kept.
class Racing(dict):
    def items(self):
        snapshot = list(super().items())
        self['k'] = (time.time(), 'new')
        return snapshot
racing = Racing(k=(old, 'stale'))
mh._prune_ttl(d, racing, 'first', 600, None, now)
check('an entry replaced during the pass is not removed', racing.get('k', (0, ''))[1] == 'new')

d._token_decimals_cache.clear()
d._token_decimals_cache.update({'m%d' % i: 6 for i in range(20001)})
mh.prune(d, now)
check('decimals (which never expire) are only capped', len(d._token_decimals_cache) == 0)
d._token_decimals_cache.update({'keep': 9}); mh.prune(d, now)
check('...and kept below the cap', d._token_decimals_cache == {'keep': 9})

check('freed heap goes back to the OS without error',
      mh.release_free_memory() in (True, False) and mh.rss_mb() > 0)

# /api/top-trades-week: same answer, without the per-trade re-scan.
from solders.keypair import Keypair  # noqa: E402
users = [str(Keypair().pubkey()) for _ in range(3)]
ids = [d.get_or_create_user(w) for w in users]
c = sqlite3.connect(d.DB_FILE)
for i, n in zip(ids, ('alice', 'bob', 'carol')):
    c.execute('UPDATE users SET username=? WHERE id=?', (n, i))
ts = lambda days: (datetime.datetime.utcnow() - datetime.timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')
rows = [(ids[0], 'BUSY', 1.0 + (k % 97) / 100, ts(1 + (k % 5))) for k in range(6000)]
rows += [(ids[0], 'BEST', 9.5, ts(2)), (ids[0], 'OLD', 99.0, ts(9)),
         (ids[1], 'BOBTOP', 4.0, ts(1)), (ids[1], 'BOBLOW', 2.0, ts(1)), (ids[1], 'LOSS', -5.0, ts(1)),
         (ids[2], 'CAROLLOSS', -1.0, ts(1))]
c.executemany("INSERT INTO trades (user_id, token, entry_price, exit_price, amount, pnl, source, chain, timestamp) "
              "VALUES (?,?,1,1,1,?,'bot','solana',?)", rows)
c.commit(); c.close()
client = app.test_client(); BASE = 'https://orcagent.fun'
with client.session_transaction(base_url=BASE) as s:
    s['wallet'] = users[2]; s['user_id'] = ids[2]; s['csrf_token'] = 'x' * 30
t0 = time.time()
r = client.get('/api/top-trades-week', base_url=BASE)
took = time.time() - t0
got = [(t['username'], t['token'], t['pnl']) for t in (r.get_json() or {}).get('trades', [])]
check('top trades of the week: each trader\'s best winning trade this week, best first',
      r.status_code == 200 and got == [('alice', 'BEST', 9.5), ('bob', 'BOBTOP', 4.0)])
check('...answered in well under a second with 6,000 trades (took %.2fs)' % took, took < 1.0)

print('%d/%d' % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
