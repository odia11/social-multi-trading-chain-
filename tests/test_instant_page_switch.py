"""Going from page to page is instant.

- No route animation: every tap on a phone used to run a 320 ms slide
  (bottom-nav tab switches included) during which the page ignored taps.
  The script that only steered that slide is gone, so no page loads it.
- No page waits on the blockchain while it renders: /profile and a public
  profile made a Solana RPC call (up to 5 s) for a balance the page never
  shows, and the profile API walked every RPC endpoint (5 s each) for a
  field nothing reads.
- Nothing is downloaded twice: Home no longer loads page-loader.js a second
  time, and the profile's tip files are warmed under the exact URL the page
  loads.
"""
import os, re, sqlite3, sys, tempfile
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck='})
import requests  # noqa: E402
outbound = []
_orig = requests.Session.request
def _spy(self, method, url, *a, **k):
    if _spy.on:
        outbound.append(str(url))
    return _orig(self, method, url, *a, **k)
_spy.on = False
requests.Session.request = _spy
import app_entry  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()

css = read('static', 'app-ux.css')
check('no route animation: view transitions are off',
      '@view-transition {\n  navigation: none;\n}' in css and 'navigation: auto' not in css
      and 'view-transition-old' not in css)
check('the slide-direction script is gone',
      not os.path.exists(os.path.join(ROOT, 'static', 'page-transition-direction.js'))
      and 'page-transition-direction' not in read('app_performance.py'))

w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
other = str(Keypair().pubkey()); d.get_or_create_user(other)
c = sqlite3.connect(d.DB_FILE)
c.execute('INSERT INTO tos_acceptances (user_id, version, accepted_at) VALUES (?,?,datetime())', (uid, d.TOS_VERSION))
c.commit(); c.close()
cl = app.test_client(); B = 'https://orcagent.fun'
with cl.session_transaction(base_url=B) as s:
    s['wallet'] = w; s['user_id'] = uid; s['csrf_token'] = 'x' * 40

home = cl.get('/', base_url=B).get_data(as_text=True)
check('no page loads the slide script', 'page-transition-direction' not in home)

for path in ('/profile', '/profile/' + other, '/api/profile/%d' % uid, '/api/profile/%d/trades' % uid):
    outbound.clear(); _spy.on = True
    r = cl.get(path, base_url=B)
    _spy.on = False
    rpc = [u for u in outbound if 'solana' in u or 'rpc' in u or 'helius' in u]
    check('%s renders without waiting on a Solana RPC call' % path.replace(other, '<wallet>').replace('/%d' % uid, '/<id>'),
          r.status_code == 200 and not rpc)

icons = read('static', 'feed-action-icons.js')
check("Home loads page-loader.js once (the shared fallback sees Home's own copy)",
      "document.querySelector('script[src^=\"/static/page-loader.js\"]')" in icons
      and '/static/page-loader.js?v=' in read('dashboard.html'))
ux = read('static', 'app-ux.js'); prof = read('templates', 'profile.html')
warm = re.search(r"'/profile':\[(.*?)\]", ux).group(1)
check("the profile's tip files are warmed under the URL the page really loads",
      # warmed as /static/<file>?v=<_APP_VERSION> (staticBuildUrl + the
      # oa-app-version meta), loaded as ?v={{ app_version }} -- the same value
      "'tip-experience.js'" in warm and '/static/tip-experience.js?v={{ app_version }}"' in prof
      and "'profile-gold-tip.css'" in warm and '/static/profile-gold-tip.css?v={{ app_version }}"' in prof
      and "return '/static/'+asset+'?v='+encodeURIComponent(APP_VERSION||'1');" in ux
      and "version = str(getattr(appmod, '_APP_VERSION', '1'))" in read('app_performance.py')
      and "'app_version': _APP_VERSION" in read('dashboard.py'))
raise SystemExit(0 if all(checks) else 1)
