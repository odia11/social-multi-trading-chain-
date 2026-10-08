"""Pages load clean on a phone: nothing on screen jumps once it is shown.

Measured as layout shift (the browser's own CLS; above 0.1 is "poor").
Before, on a 390px phone:
- Home 0.72 and Settings 0.71: the feed was drawn at the top, then the mobile
  Home inserted its blocks above it;
- Portfolio up to 1.0, Deposit 0.99, Withdraw 0.71: the header lost its
  search row only once a page script ran, and Portfolio was rebuilt after load;
- Live Market 0.6: its mobile classes, quick filters, Top traders rail and the
  search field's final height all arrived after the first paint;
- Terms/Privacy/Fees/Security/Contact 0.3-0.56: the webfont swapped in and
  re-flowed the whole page (display=swap);
- Bot 0.2, Groups 0.1, Profile 0.1: lists and styles that came in late.
"""
import json, os, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
checks = []
def check(name, cond, detail=''):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name + ((' -- %s' % detail) if detail and not cond else ''), flush=True)

PERF = open(os.path.join(ROOT, 'app_performance.py'), encoding='utf-8').read()
check('webfonts never swap in on a page already on screen', "display=optional" in PERF)
for tpl in ('profile.html', 'wallet.html'):
    t = open(os.path.join(ROOT, 'templates', tpl), encoding='utf-8').read()
    check('%s: its tip/balance styles load in the head' % tpl,
          t.index('tip-experience.css') < t.index('</head>'))

PORT = 5104
ENV = dict(os.environ, DATA_DIR=tempfile.mkdtemp(), ENCRYPTION_KEY='6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
           ORCAGENT_FRONTS_GAS='0', ORCAGENT_PLATFORM_POSTS='0', PYTHONPATH=ROOT)
SEED = r'''
import os, sys, sqlite3, json
sys.path.insert(0, %r)
import app_entry
d = app_entry._dashboard; app = app_entry.app
from solders.keypair import Keypair
w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
c = sqlite3.connect(d.DB_FILE)
c.execute('INSERT INTO tos_acceptances (user_id, version, accepted_at) VALUES (?,?,datetime())', (uid, d.TOS_VERSION))
c.execute("UPDATE users SET username='loadtester' WHERE id=?", (uid,))
for i in range(8):
    c.execute("INSERT INTO feed_posts (wallet, content) VALUES (?,?)", (w, 'Post %%d about the market today' %% i))
c.commit(); c.close()
with app.test_request_context():
    from flask import session
    session['wallet'] = w; session['csrf_token'] = 'x' * 64; session.permanent = True
    resp = app.response_class(); app.session_interface.save_session(app, session, resp)
    print('@@' + resp.headers['Set-Cookie'].split(';')[0].split('=', 1)[1])
os._exit(0)
''' % ROOT
r = subprocess.run([sys.executable, '-c', SEED], env=ENV, capture_output=True, text=True, timeout=180)
COOKIE = ([l[2:] for l in r.stdout.splitlines() if l.startswith('@@')] or [''])[-1]
server = subprocess.Popen([sys.executable, '-c',
    'import app_entry as d;d._dashboard._rate_ok=lambda *a,**k:True;'
    'd.app.run(host="127.0.0.1",port=%d,debug=False,use_reloader=False,threaded=True)' % PORT],
    env=ENV, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

DRIVER = r'''
import asyncio, json, os, time
from playwright.async_api import async_playwright
PORT, COOKIE = %d, %r
PAGES = ['/', '/wallet', '/live-market', '/live-market', '/info#terms', '/groups', '/bot', '/profile', '/settings']
INIT = """window.__cls=0;try{new PerformanceObserver(l=>l.getEntries().forEach(e=>{if(!e.hadRecentInput)window.__cls+=e.value})).observe({type:'layout-shift',buffered:true})}catch(e){}"""
now = int(time.time() * 1000)
TOK = [{'mint': 'Mint%%02d' %% i + 'x' * 36, 'symbol': 'TK%%d' %% i, 'name': 'Token %%d' %% i, 'chain': 'solana', 'dex_id': 'raydium',
        'pair_address': 'Pair%%02d' %% i + 'y' * 36, 'image_url': '', 'price_usd': 0.001 * (i + 1), 'market_cap': 1e6 * (i + 1),
        'liquidity_usd': 2e5, 'volume_24h': 5e5, 'buys_24h': 300, 'sells_24h': 200, 'price_change_24h': 12.5,
        'pair_created_at': now - 86400000, 'verified_socials': True, 'score': 4} for i in range(4)]
async def main():
    async with async_playwright() as p:
        try:
            b = await p.chromium.launch(args=['--no-sandbox'])
        except Exception:
            b = await p.chromium.launch(args=['--no-sandbox'], executable_path=os.environ.get('CHROMIUM_PATH') or '/opt/pw-browsers/chromium')
        ctx = await b.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        await ctx.add_init_script("try{localStorage.setItem('orcagent_tips_seen','1');localStorage.setItem('orca_wizard_dismissed','1')}catch(e){}")
        await ctx.add_init_script(INIT)
        await ctx.add_cookies([{'name': 'orca_s', 'value': COOKIE, 'domain': '127.0.0.1', 'path': '/'}])
        await ctx.route('**/api/market/scanner*', lambda r: r.fulfill(status=200, content_type='application/json',
                        body=json.dumps({'ok': True, 'tokens': TOK, 'counts': {'trending': 4}})))
        page = await ctx.new_page(); out = {}
        for i, path in enumerate(PAGES):
            await page.goto('http://127.0.0.1:%%d%%s' %% (PORT, path), wait_until='load')
            await page.wait_for_timeout(2600)
            out['%%d %%s' %% (i, path)] = round(await page.evaluate('window.__cls'), 3)
        await b.close()
    print('@@' + json.dumps(out))
asyncio.run(main())
''' % (PORT, COOKIE)

B = {}
try:
    for _ in range(60):
        try:
            urllib.request.urlopen('http://127.0.0.1:%d/static/og-orcagent.png' % PORT, timeout=2); break
        except Exception:
            time.sleep(1)
    r = subprocess.run([sys.executable, '-c', DRIVER], capture_output=True, text=True, timeout=400)
    line = [l for l in r.stdout.splitlines() if l.startswith('@@')]
    B = json.loads(line[-1][2:]) if line else {}
    if not B: print(r.stdout[-1500:], r.stderr[-1500:])
finally:
    server.terminate()

print('measured:', json.dumps(B))
names = {'/': 'Home', '/wallet': 'Portfolio', '/live-market': 'Live Market', '/info#terms': 'Terms',
         '/groups': 'Groups', '/bot': 'Bot', '/profile': 'Profile', '/settings': 'Settings'}
for key, cls in sorted(B.items(), key=lambda kv: int(kv[0].split()[0])):
    path = key.split(' ', 1)[1]
    label = names.get(path, path) + (' (second visit)' if path == '/live-market' and key.startswith('3 ') else '')
    check('BROWSER: %s loads without a visible jump (layout shift %.3f, at most 0.1)' % (label, cls), cls <= 0.1)
check('BROWSER: every page was measured', len(B) == 9)

print('%d/%d' % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
