"""A user never sees a bare {"error": ...} page or giant unstyled icons.

Opening pages quickly from one address made the global rate limit answer
the page itself with {"error":"Too many requests"} on a white screen, and
the stylesheets with the same, so the menu icons rendered screen-filling.

- The global limit counts a signed-in member per account (people on one
  mobile network or Wi-Fi share an IP), and never counts static files or
  the light-mode stylesheets.
- When the page the browser navigates to is refused anyway, it gets a small
  OrcAgent page with the same status; a 429 reloads itself. Fetches from the
  app still get JSON.
- Server-rendered menu icons carry their own size, so they stay small even
  if a stylesheet does not arrive; and when a page's stylesheets did not
  arrive, it is covered by an OrcAgent screen and reloaded (twice at most,
  then a "Try again" button) instead of showing raw markup.
"""
import os, re, sys, tempfile
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_PLATFORM_POSTS': '0'})
import app_entry  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
d = app_entry._dashboard
app = app_entry.app

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

BASE = 'https://orcagent.fun'
NAV = {'Sec-Fetch-Dest': 'document', 'Accept': 'text/html,application/xhtml+xml'}
FETCH = {'Sec-Fetch-Dest': 'empty', 'Accept': '*/*'}
wa, wb = str(Keypair().pubkey()), str(Keypair().pubkey())
ua, ub = d.get_or_create_user(wa), d.get_or_create_user(wb)

def client_for(wallet, uid):
    c = app.test_client()
    with c.session_transaction(base_url=BASE) as s:
        s['wallet'] = wallet; s['user_id'] = uid; s['csrf_token'] = 'x' * 30
    return c

# Two members behind one address: A uses up more than the old per-IP budget.
ca, cb = client_for(wa, ua), client_for(wb, ub)
same_ip = {'REMOTE_ADDR': '203.0.113.7'}
d._rl_hits.clear()
codes = [ca.get('/api/push/vapid-public-key', base_url=BASE, environ_base=same_ip, headers=FETCH).status_code
         for _ in range(d.GLOBAL_LIMIT_ANON + 20)]
check('a busy member is not cut off at the per-IP limit (%d requests)' % len(codes), 429 not in codes)
check('...and someone else on the same address is not affected either',
      cb.get('/api/push/vapid-public-key', base_url=BASE, environ_base=same_ip, headers=FETCH).status_code != 429)
check('members are counted per account, not per address',
      'global:w:' + wa in d._rl_hits and 'global:203.0.113.7' not in d._rl_hits)
anon = app.test_client()
anon.get('/static/navbar.css', base_url=BASE, environ_base=same_ip)
anon.get('/theme-light/navbar.css', base_url=BASE, environ_base=same_ip)
check('static files and light-mode stylesheets are never counted',
      'global:203.0.113.7' not in d._rl_hits)
check('signed-out visitors still have a per-address limit',
      d.GLOBAL_LIMIT_ANON <= 500 and d.GLOBAL_LIMIT_MEMBER > d.GLOBAL_LIMIT_ANON)

# Refused anyway: the page navigation gets an OrcAgent page.
real = d._rate_ok
d._rate_ok = lambda key, limit, window: not key.startswith('global:') and real(key, limit, window)
try:
    page = ca.get('/wallet', base_url=BASE, headers=NAV)
    body = page.get_data(as_text=True)
    check('a refused page answers 429 with an HTML page, not JSON',
          page.status_code == 429 and page.mimetype == 'text/html' and '{"error"' not in body)
    check('...that says "One moment" and reloads itself',
          'One moment' in body and 'http-equiv="refresh"' in body and page.headers.get('Retry-After'))
    own = body.split('<main>', 1)[0]
    check('...with its own look inline, so it is right even when nothing else loads',
          '<style>' in own and 'background:#0a0b0e' in own and 'href="/static/navbar.css' not in body)
    api = ca.get('/api/me', base_url=BASE, headers=FETCH)
    check('a fetch from the app still gets JSON it can handle',
          api.status_code == 429 and api.is_json and api.get_json().get('error'))
    api_nav = ca.get('/api/me', base_url=BASE, headers=NAV)
    check('...and so does an API address opened directly', api_nav.is_json)
finally:
    d._rate_ok = real

nav = str(d._navbar_html('feed'))
svgs = re.findall(r'<svg[^>]*>', nav)
check('every server-rendered menu icon has its own size (%d icons)' % len(svgs),
      svgs and all(re.search(r'\bwidth="\d+"', s) and re.search(r'\bheight="\d+"', s) for s in svgs))

check('every page with the menu checks that its stylesheets really arrived',
      nav.startswith('<script>') and "!links[i].sheet" in nav and "'/static/'" in nav and "'/theme-light/'" in nav)
check('...and if not, covers the raw page, reloads at most twice, then offers "Try again"',
      "id='oa-css-cover'" in nav and 'if(tries<2)' in nav and "'Try again'" in nav
      and nav.index('<script>') < nav.index('navbar.css'))

print('%d/%d' % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
