"""The server keeps answering when it is busy, and the feed stays fast as it grows.

Measured on a copy with 3,000 members, 20,000 posts and 150,000 likes, with
the production setup (one gunicorn worker, 16 threads):

- one Home feed request took 8-10 s: every like, reply and repost it counted
  was checked against its post with `'p'||id = post_id`, which cannot use the
  primary key, so SQLite scanned all posts for each of them;
- with Live Market's token list empty (a restart, or DexScreener answering
  nothing) every Live Market request queued on one lock behind a network call
  and then tried the network again itself; the X buzz list, refreshed every
  15 minutes, made the first Home visitor wait for a web search while every
  other visitor waited on its lock; a balance read the RPC could not answer
  held a thread for seconds on every poll of every tab. Each of these could
  take all 16 threads, and then the whole app stood still;
- a dozen per-request costs: a database write lock on every signed-in request
  (invitation bookkeeping), a remembered-login token minted by each of the
  dozen parallel requests of one page, a renewal write on every page view, a
  database write for every request a bot or scanner sent.

100 simulated users browsing: from 48 to 83 requests/s, median wait from 12 s
to 1 s. 100 polling tabs: from 52 to 155 requests/s.
"""
import json, os, sqlite3, sys, tempfile, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_TRENDING_ALERTS': '0', 'ORCAGENT_PLATFORM_POSTS': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond, detail=''):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name + ((' -- %s' % detail) if detail and not cond else ''), flush=True)

# ── the feed: same answer, read off the indexes ─────────────────────────────
c = sqlite3.connect(d.DB_FILE)
plan = ' '.join(r[3] for r in c.execute(
    'EXPLAIN QUERY PLAN SELECT pl.post_id FROM post_likes pl WHERE pl.post_id IN (?,?) AND '
    + d._valid_post_interaction_sql('pl'), ('p1', 'p2')))
check("a like's post is looked up by its primary key, not by scanning every post",
      'feed_posts USING INTEGER PRIMARY KEY' in plan and 'SCAN feed_posts' not in plan, plan)
norm = "(CASE WHEN fp.created_at LIKE '%T%' THEN replace(replace(fp.created_at,'T',' '),'Z','') ELSE fp.created_at END)"
plan = ' '.join(r[3] for r in c.execute('EXPLAIN QUERY PLAN SELECT fp.id FROM feed_posts fp ORDER BY ' + norm + ' DESC LIMIT 20'))
check('the newest posts come straight off an index (no sort of every post)', 'idx_feed_posts_norm_ts' in plan, plan)

# Mixed timestamp formats, trades and reposts: the feed must be exactly the
# newest rows of all three, in order, page after page.
users = [str(Keypair().pubkey()) for _ in range(4)]
for w in users:
    d.get_or_create_user(w)
uid = {w: c.execute('SELECT id FROM users WHERE wallet_address=?', (w,)).fetchone()[0] for w in users}
expected = []
for i in range(60):
    w = users[i % 4]
    ts = '2026-09-%02d %02d:%02d:00' % (1 + i // 4, i % 24, i % 60)
    stamp = ts.replace(' ', 'T') + 'Z' if i % 3 == 0 else ts       # every third written the ISO way
    pid = c.execute('INSERT INTO feed_posts (wallet, content, created_at) VALUES (?,?,?)', (w, 'post %d' % i, stamp)).lastrowid
    expected.append((ts, 'p', pid))
    if i % 5 == 0:
        tid = c.execute("INSERT INTO trades (user_id, token, timestamp, entry_price, exit_price) VALUES (?,?,?,1,2)",
                        (uid[w], 'TK', ts.replace('00', '30', 1))).lastrowid
        expected.append((ts.replace('00', '30', 1), 't', tid))
    if i % 7 == 0 and i:
        rid = c.execute('INSERT INTO feed_reposts (post_id, reposter_wallet, created_at) VALUES (?,?,?)',
                        ('p%d' % pid, users[(i + 1) % 4], ts.replace(':00', ':01', 1))).lastrowid
        expected.append((ts.replace(':00', ':01', 1), 'r', rid))
c.commit()
expected.sort(reverse=True)
client = app.test_client()
got, cursor = [], ''
for _ in range(8):
    url = '/api/social/feed?limit=10' + ('&before=' + cursor if cursor else '')
    data = client.get(url).get_json()
    items = data.get('items') or []
    if not items:
        break
    got += [(i['type'] == 'repost' and 'r' or (i['type'] == 'trade' and 't' or 'p'), i['id']) for i in items]
    cursor = items[-1]['created_at']
check('the feed is exactly the newest posts, trades and reposts, in order, across pages',
      got[:len(expected)] == [(k, i) for _, k, i in expected][:len(got)] and len(got) >= 60,
      str(got[:12]) + ' vs ' + str([(k, i) for _, k, i in expected][:12]))
c.close()

# ── Live Market's token list never makes everyone wait ───────────────────────
calls = []
def slow_empty():
    calls.append(time.time()); time.sleep(1.5); return []
d._get_scanner_candidates = slow_empty
d._scanner_cache.update({'ts': 0.0, 'data': []}); d._scanner_cache.pop('attempt_ts', None)
done = []
def ask():
    t = time.time(); d._get_scanner_cached(); done.append(time.time() - t)
threads = [threading.Thread(target=ask) for _ in range(10)]
t0 = time.time()
[t.start() for t in threads]; [t.join() for t in threads]
check('with no token list yet, one request fetches and the others are answered within seconds',
      len(calls) == 1 and max(done) < 3.0 and time.time() - t0 < 3.5, '%d fetches, slowest %.1fs' % (len(calls), max(done)))
t = time.time(); d._get_scanner_cached()
check('...and an empty answer is not fetched again by the very next request', len(calls) == 1 and time.time() - t < 0.2)

# ── the X buzz list: an expired list is served at once ───────────────────────
slow = threading.Event()
d._discover_x_buzz = lambda: (time.sleep(1.5), slow.set(), ['WIF'])[2]
d._resolve_buzz_pairs = lambda tickers, chains: [{'mint': 'M', 'symbol': 'WIF', 'chain': 'solana'}]
with d._buzz_lock:
    d._buzz_cache.update({'ts': time.time() - d._BUZZ_TTL - 5, 'data': [{'mint': 'OLD', 'symbol': 'OLD', 'chain': 'solana'}]})
t = time.time(); first = d.get_multichain_x_buzz(); waited = time.time() - t
check('an expired buzz list is returned at once and refreshed in the background (no visitor waits on the search)',
      waited < 0.3 and first[0]['mint'] == 'OLD', '%.2fs' % waited)
slow.wait(5); time.sleep(0.2)
check('...and the refreshed list is there for the next visitor', d.get_multichain_x_buzz()[0]['mint'] == 'M')

# ── a balance the RPC cannot read does not hold a thread on every poll ───────
import portfolio_multichain_holdings as pm
inflight, peak, fetches = [0], [0], [0]
lock = threading.Lock()
def failing_fetch(wallet, owner=None):
    with lock:
        inflight[0] += 1; peak[0] = max(peak[0], inflight[0]); fetches[0] += 1
    time.sleep(0.6)
    with lock:
        inflight[0] -= 1
    raise RuntimeError('rpc down')
d._fetch_wallet_tokens = failing_fetch
d._get_trading_wallet_address = lambda w: w
wallets = [str(Keypair().pubkey()) for _ in range(14)]
def snap(w):
    try:
        pm._portfolio_snapshot(d, w)
    except RuntimeError:
        pass
threads = [threading.Thread(target=snap, args=(w,)) for w in wallets]
[t.start() for t in threads]; [t.join() for t in threads]
check('at most 6 balance reads talk to the RPC at once; the rest answer at once', peak[0] <= 6, 'peak %d' % peak[0])
before = fetches[0]; t = time.time(); snap(wallets[0])
check('...and a wallet whose read just failed is not read again on the next poll',
      fetches[0] == before and time.time() - t < 0.1)

# ── per-request costs ────────────────────────────────────────────────────────
c = sqlite3.connect(d.DB_FILE)
rows_before = c.execute("SELECT COUNT(*) FROM security_log WHERE event_type='bot_probe'").fetchone()[0]
for _ in range(25):
    client.get('/api/version', headers={'User-Agent': 'curl/8.5.0'})
rows = c.execute("SELECT COUNT(*) FROM security_log WHERE event_type='bot_probe'").fetchone()[0] - rows_before
check('a bot sending 25 requests is logged once, not 25 database writes', rows == 1, str(rows))

me = str(Keypair().pubkey()); d.get_or_create_user(me)
seen = []
import call_invitations
real_complete = call_invitations.complete_signup
call_invitations.complete_signup = lambda *a, **k: (seen.append(1), real_complete(*a, **k))[1]
with app.test_request_context():
    from flask import session
    session['wallet'] = me; session['user_id'] = d._get_uid(c, me); session['csrf_token'] = 'x' * 40
    resp = app.response_class(); app.session_interface.save_session(app, session, resp)
    cookie = resp.headers['Set-Cookie'].split(';')[0].split('=', 1)[1]
minted_before = c.execute('SELECT COUNT(*) FROM device_sessions WHERE wallet=?', (me,)).fetchone()[0]
for _ in range(12):   # a page's parallel requests: none carries the remembered-login cookie yet
    tab = app.test_client()
    tab.set_cookie(app.config.get('SESSION_COOKIE_NAME', 'session'), cookie, domain='orcagent.fun')
    tab.get('/api/messages/unread_count', base_url='https://orcagent.fun', headers={'User-Agent': 'Mozilla/5.0 Safari'})
minted = c.execute('SELECT COUNT(*) FROM device_sessions WHERE wallet=?', (me,)).fetchone()[0] - minted_before
check("one browser's burst of requests mints one remembered login, not one each", minted == 1, str(minted))
check('invitation bookkeeping runs once per account, not on every request', len(seen) == 1, str(len(seen)))
c.close()

src = open(os.path.join(os.path.dirname(__file__), '..', 'dashboard.py'), encoding='utf-8').read()
check('a remembered login is renewed at most hourly, not written on every page view',
      'if now - float(last_used_at or 0) >= DEVICE_RENEW_SECONDS:' in src and 'DEVICE_RENEW_SECONDS = 3600' in src)

# ── the response body is decoded once for all the page hooks ─────────────────
r = app.response_class('<html><head></head><body>é</body></html>', mimetype='text/html')
a = r.get_data(as_text=True); b = r.get_data(as_text=True)
check('a page body read twice as text is decoded once', a is b)
r.set_data(a.replace('</body>', 'x</body>'))
check('...and a changed body is what the next hook reads', r.get_data(as_text=True).endswith('x</body></html>')
      and r.get_data() == r.get_data(as_text=True).encode('utf-8'))

print('%d/%d' % (sum(checks), len(checks)))
os._exit(0 if all(checks) else 1)
