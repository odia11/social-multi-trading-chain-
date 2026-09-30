"""Security round: XSS, injection and information leaks.

What was checked across the app, and what this pins:
- SQL: every query is parameterised; identifiers come from allowlists. An
  injection payload in search is just text.
- Shared post page (/post/<id>): the post image goes into <meta> attributes
  of a page whose every <script> gets a CSP nonce, so a quote in it must be
  escaped (it used to be pasted in raw).
- Home: the session wallet is written into JavaScript string literals; it is
  JS-encoded so a quote, backslash or </script> could never break out.
- Error responses: an unexpected 500 on a member route no longer returns the
  raw exception (SQL, paths, provider data) -- a generic message, and the
  real reason in the server log. The wallet/referrals HTML error pages no
  longer echo the exception either.
- Browser: every HTML escape helper escapes both quote kinds; the Home token
  card only links http(s) URLs chosen by token creators (never javascript:);
  the Portfolio top-trader rows escape name, handle and avatar.
- Admin API: refused for a normal member.
"""
import os, re, sqlite3, sys, tempfile, glob
from unittest.mock import patch
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
B = 'https://orcagent.fun'

w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
c = sqlite3.connect(d.DB_FILE)
c.execute('INSERT INTO tos_acceptances (user_id, version, accepted_at) VALUES (?,?,datetime())', (uid, d.TOS_VERSION))
c.execute("UPDATE users SET username='alice' WHERE id=?", (uid,))
evil_img = 'https://cdn.example/a.png" onerror="alert(1)" x="'
pid = c.execute("INSERT INTO feed_posts (wallet, content, created_at, image_url) VALUES (?,?,datetime(),?)",
                (w, 'hello', evil_img)).lastrowid
c.commit(); c.close()

def member(wallet=w, uid_=uid):
    cl = app.test_client()
    with cl.session_transaction(base_url=B) as s:
        s['wallet'] = wallet; s['user_id'] = uid_; s['csrf_token'] = 'x' * 40
    return cl

page = app.test_client().get('/post/p%d' % pid, base_url=B).get_data(as_text=True)
check('a quote in a post image cannot break out of the share page <meta> tags',
      'onerror="alert(1)"' not in page and '&quot; onerror=&quot;alert(1)&quot;' in page)

cl = member()
r = cl.get("/api/users/search?q=' OR 1=1 --", base_url=B)
check('an SQL injection payload in search is just text (no error, no dump)',
      r.status_code == 200 and r.get_json()['users'] == [])

with patch.object(d, '_get_uid', side_effect=RuntimeError('no such table: secret_internal at /data/orcagent.db')):
    r = cl.get('/api/users/search?q=bob', base_url=B)
body = r.get_data(as_text=True)
check('an unexpected 500 on a member route hides the exception and says something generic',
      r.status_code == 500 and 'secret_internal' not in body and '/data/' not in body
      and 'Something went wrong on our side' in body)
src = read('dashboard.py')
member_500 = []
lines = src.split('\n')
for i, l in enumerate(lines):
    if re.search(r"return jsonify\(\{[^}]*(str\(e\)|\{e\})[^}]*\}\),\s*500\s*$", l):
        j = i
        while '@app.route(' not in lines[j]: j -= 1
        route = re.search(r"@app\.route\('([^']+)'", lines[j]).group(1)
        if not (route.startswith('/api/admin') or route.startswith('/api/audit')):
            member_500.append(route)
check('no member route returns raw exception text on a 500', member_500 == [])
check('the wallet and referrals error pages no longer echo the exception',
      "<h1>Wallet Error: {str(e)}</h1>" not in src and "<h1>Referrals Error: {str(e)}</h1>" not in src)

odd = "abc'</script><img src=x onerror=alert(1)>"
home = member(odd, uid).get('/', base_url=B).get_data(as_text=True)
check("the session wallet is JS-encoded where Home writes it into a script",
      odd not in home and "abc\\u0027\\u003c/script\\u003e" in home)

helpers = []
for f in glob.glob(os.path.join(ROOT, 'static', '*.js')) + glob.glob(os.path.join(ROOT, 'templates', '*.html')) + [os.path.join(ROOT, 'dashboard.html')]:
    for m in re.finditer(r"function (esc|_esc|_e|escHtml|escapeHtml|_ltEsc|_escHtml|htmlEsc|_supEsc)\([a-z]+\)\s*\{[^}]{0,260}\}", open(f, encoding='utf-8').read()):
        helpers.append((os.path.basename(f), m.group(0)))
bad = [f for f, h in helpers if not ('&#39;' in h or '&#x27;' in h) or "'&quot'" in h]
check('every HTML escape helper escapes both quote kinds (%d helpers)' % len(helpers), helpers and not bad)
dash = read('static', 'dashboard.js')
check("the Home token card only links http(s) URLs chosen by token creators",
      ".filter(function(l){return l && typeof l.url==='string' && /^https?:\\/\\//i.test(l.url.trim())})" in dash)
wal = read('templates', 'wallet.html')
check('Portfolio top-trader rows escape name, handle and avatar',
      "'<div class=\"sb-tr-name\">'+esc(name)+'</div>'" in wal and "src=\"'+esc(t.avatar_url)+'\"" in wal
      and "'<div class=\"sb-tr-handle\">'+esc(handle)+'</div>'" in wal)
check("the trending share page's redirect script cannot be closed by its data",
      'json.dumps(target).replace("<", chr(92) + "u003c")' in read('trending_share.py'))

for path in ('/api/admin/users', '/api/admin/revenue', '/api/admin/trades'):
    code = cl.get(path, base_url=B).status_code
    if code not in (401, 403):
        check('admin API refuses a normal member: ' + path, False)
        break
else:
    check('the admin API refuses a normal member', True)
raise SystemExit(0 if all(checks) else 1)
