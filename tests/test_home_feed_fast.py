"""Home's feed arrives first and fast, the way big feeds load.

It used to be the ~100th request of a Home load, sent only after the
session check, the Terms check and a second state read. It was one 200-row
page in which bot trades (which Home never shows) crowded out the posts, on
a server with 4 request threads for everyone. Under load that was a long
"Loading...". Now:
- the page's <head> requests the first feed page before anything else;
- loadHomeFeed() uses that response and starts at the top of launchApp()
  (on a microtask, after dashboard.js has finished evaluating);
- the last feed this member saw is painted from the device right away
  (stale-while-revalidate, per wallet, max 6 hours), then refreshed;
- the API gives posts only and a phone-sized page (40); older posts come
  with infinite scroll. Other callers get the old behaviour;
- the server has 16 request threads in its one worker (the loops still run
  once);
- the old dashboard's trade table, activity log, Refresh and Solscan are
  hidden on Home.
"""
import os, re, sqlite3, subprocess, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck='})
import app_entry  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()

w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
c = sqlite3.connect(d.DB_FILE)
c.executemany("INSERT INTO trades (user_id, token, entry_price, exit_price, amount, pnl, source, chain, base_currency, timestamp) "
              "VALUES (?, 'BOT', 1, 1.1, 10, 1, 'bot', 'solana', 'USDC', datetime('now', ?))",
              [(uid, '-%d seconds' % (i * 10)) for i in range(400)])
c.executemany("INSERT INTO feed_posts (wallet, content, created_at) VALUES (?, ?, datetime('now', ?))",
              [(w, 'post %d' % i, '-%d seconds' % (i * 600)) for i in range(60)])
c.commit(); c.close()
cl = app.test_client(); B = 'https://orcagent.fun'
old = cl.get('/api/social/feed?filter=all', base_url=B).get_json()
check('without the new parameters the feed is unchanged: 200 rows, bot trades crowding out posts',
      len(old['items']) == 200 and sum(1 for i in old['items'] if i['type'] == 'trade') > 150)
new = cl.get('/api/social/feed?filter=all&kinds=posts&limit=40', base_url=B).get_json()
check("Home's request gets 40 posts and no bare trades",
      len(new['items']) == 40 and not any(i['type'] == 'trade' for i in new['items'])
      and new['items'][0]['content'].startswith('post 0'))
page2 = cl.get('/api/social/feed?filter=all&kinds=posts&limit=40&before=' + new['next_cursor'], base_url=B).get_json()
check('...and the next 20 with infinite scroll, none repeated',
      len(page2['items']) == 20 and not ({i['id'] for i in page2['items']} & {i['id'] for i in new['items']}))
check('a nonsense limit falls back safely',
      len(cl.get('/api/social/feed?filter=all&kinds=posts&limit=abc', base_url=B).get_json()['items']) == 60
      and len(cl.get('/api/social/feed?filter=all&kinds=posts&limit=1', base_url=B).get_json()['items']) == 10)

html = read('dashboard.html'); js = read('static', 'dashboard.js')
head = html[:html.index('</head>')]
check("the page's <head> asks for the feed before any other script",
      "var url='/api/social/feed?filter=all&kinds=posts&limit=40';" in head
      and head.index('__oaFeedEarly') < head.index('<script src='))
check('...and loadHomeFeed() uses it only when it asked for the very same URL',
      'var HOME_FEED_PAGE=40;' in js and "url+='&kinds=posts&limit='+HOME_FEED_PAGE;" in js
      and "if(early && filter==='all' && _homeFeedUrl('all')===early.url) data=await early.data;" in js
      and 'fetch(_homeFeedUrl(filter, _homeFeedNextCursor)' in js)
launch = js[js.index('async function launchApp(){'):]
launch = launch[:launch.index('\n}\n')]
check('launchApp() starts the feed first, after the script has finished evaluating',
      launch.index("Promise.resolve().then(function(){ return _safeInit('loadHomeFeed', loadHomeFeed()); });")
      < launch.index("await fetch('/api/state')")
      and "if(_feedNeedsReload) _safeInit('loadHomeFeed', loadHomeFeed());" in launch
      and '_feedNeedsReload=true;' in launch)
check("the last feed is painted from this device (this member's only, at most 6 hours old)",
      "localStorage.getItem('oa_feed_v1:'+filter)" in js and 'c.w!==_homeFeedViewer()' in js
      and 'var HOME_FEED_CACHE_TTL=6*3600*1000;' in js and '_homeFeedCacheWrite(filter, data);' in js)

svc = read('deploy', 'orcagent.service')
check('the server has 16 request threads in its single worker',
      '--workers 1 \\' in svc and '--threads 16 \\' in svc and '--workers 1 --threads 16' in read('Procfile'))
check("the old dashboard's trade table, activity log, Refresh and Solscan are hidden on Home",
      '.oa-retired{display:none!important}' in html
      and '<div class="trade-table-wrap oa-retired">' in html
      and '<div class="panels oa-retired"' in html and '<div class="bottom oa-retired">' in html
      and 'id="log-body"' in html and 'id="btn-solscan"' in html)
r = subprocess.run(['node', '--check', os.path.join(ROOT, 'static', 'dashboard.js')], capture_output=True, text=True)
check('dashboard.js still parses', r.returncode == 0)
raise SystemExit(0 if all(checks) else 1)
