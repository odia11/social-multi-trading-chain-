"""Tapping $Attention+ in an @orcagent post opens that call -- in a real feed.

The post "$Attention+ just hit 10x since @degentrader1990 called it" linked
only "$Attention" (the plus fell off) and searched for a token by that name,
because the picture that replaced its call card had taken the call marker
with it. Now the post keeps the marker, its picture still stands in for the
card, and the whole ticker opens the caller's own call post.
"""
import json, os, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

PORT = 5102
DATA = tempfile.mkdtemp()
ENV = dict(os.environ, DATA_DIR=DATA, ENCRYPTION_KEY='6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
           ORCAGENT_FRONTS_GAS='0', ORCAGENT_PLATFORM_POSTS='0', PYTHONPATH=ROOT)
SEED = r'''
import os, sys, sqlite3, json
sys.path.insert(0, %r)
import app_entry, platform_assistant
d = app_entry._dashboard; app = app_entry.app
from solders.keypair import Keypair
me_w, agent_w, caller_w = (str(Keypair().pubkey()) for _ in range(3))
me, agent, caller = d.get_or_create_user(me_w), d.get_or_create_user(agent_w), d.get_or_create_user(caller_w)
c = sqlite3.connect(d.DB_FILE)
c.execute('INSERT INTO tos_acceptances (user_id, version, accepted_at) VALUES (?,?,datetime())', (me, d.TOS_VERSION))
c.execute("UPDATE users SET username='Orcagent', is_verified=1 WHERE id=?", (agent,))
c.execute("UPDATE users SET username='degentrader1990' WHERE id=?", (caller,))
c.commit(); c.close()
platform_assistant.initialize(d.DB_FILE)
c = sqlite3.connect(d.DB_FILE)
platform_assistant.identity(c)   # pins @orcagent as the official author
MINT = 'AttnPLUSmint1111111111111111111111111111111'[:44]
call_post = c.execute("INSERT INTO feed_posts (wallet, content, created_at) VALUES (?,?,datetime('now','-3 days'))",
                      (caller_w, 'Strong community, early.\n__CALL__{"id": 0}')).lastrowid
cid = c.execute("INSERT INTO token_calls (user_id, wallet, mint, symbol, token_name, price_at_call, mcap_at_call, peak_price,"
                " timestamp, note, post_id, chain, last_price) VALUES (?,?,?,?,?,?,?,?,datetime('now','-3 days'),?,?,?,?)",
                (caller, caller_w, MINT, 'Attention+', 'Attention', 0.0000188, 18800, 0.000939, 'Strong community, early.',
                 call_post, 'solana', 0.000261)).lastrowid
c.execute('UPDATE feed_posts SET content=? WHERE id=?', ('Strong community, early.\n__CALL__' + json.dumps({'id': cid}), call_post))
text = '$Attention+ just hit 10x since @degentrader1990 called it at a $18.8K market cap. Open the call to see the entry and the reasoning.'
agent_post = c.execute("INSERT INTO feed_posts (wallet, content, image_url) VALUES (?,?,?)",
                       (agent_w, text + '\n__CALL__' + json.dumps({'id': cid}), '/static/og-orcagent.png')).lastrowid
c.execute('INSERT INTO platform_assistant_events VALUES(?,?,?,?,?,?,?)', ('slot', 'post', None, 'p%%d' %% agent_post, None, 'milestone:%%d:10' %% cid, 0))
c.commit(); c.close()
with app.test_request_context():
    from flask import session
    session['wallet'] = me_w; session['csrf_token'] = 'x' * 64; session.permanent = True
    resp = app.response_class(); app.session_interface.save_session(app, session, resp)
    print('@@' + json.dumps({'cookie': resp.headers['Set-Cookie'].split(';')[0].split('=', 1)[1],
                             'agent_post': agent_post, 'call_post': call_post}))
os._exit(0)
''' % ROOT
r = subprocess.run([sys.executable, '-c', SEED], env=ENV, capture_output=True, text=True, timeout=180)
SEEDED = json.loads(([l[2:] for l in r.stdout.splitlines() if l.startswith('@@')] or ['{}'])[-1])
if not SEEDED: print(r.stdout[-1500:], r.stderr[-1500:])
server = subprocess.Popen([sys.executable, '-c',
    'import app_entry as d;d._dashboard._rate_ok=lambda *a,**k:True;'
    'd.app.run(host="127.0.0.1",port=%d,debug=False,use_reloader=False,threaded=True)' % PORT],
    env=ENV, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

DRIVER = r'''
import asyncio, json, os
from playwright.async_api import async_playwright
PORT, S = %d, %s
async def main():
    async with async_playwright() as p:
        try:
            b = await p.chromium.launch(args=['--no-sandbox'])
        except Exception:
            b = await p.chromium.launch(args=['--no-sandbox'], executable_path=os.environ.get(
                'CHROMIUM_PATH') or '/opt/pw-browsers/chromium')
        ctx = await b.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        await ctx.add_init_script("try{localStorage.setItem('orcagent_tips_seen','1');localStorage.setItem('orca_wizard_dismissed','1')}catch(e){}")
        await ctx.add_cookies([{'name': 'orca_s', 'value': S['cookie'], 'domain': '127.0.0.1', 'path': '/'}])
        page = await ctx.new_page(); errs = []
        page.on('pageerror', lambda e: errs.append(str(e)[:160]))
        await page.goto('http://127.0.0.1:%%d/' %% PORT, wait_until='load')
        card = '#fc-card-p%%d' %% S['agent_post']
        await page.wait_for_selector(card, timeout=30000)
        await page.wait_for_timeout(1200)
        out = await page.evaluate("""(sel) => { const c = document.querySelector(sel);
            return {tags: [...c.querySelectorAll('.token-tag')].map(t => t.textContent),
                    picture: !!c.querySelector('.fc-post-image'), card: !!c.querySelector('.fcall-card'),
                    text: c.textContent.includes('just hit 10x') && !c.textContent.includes('__CALL__')}; }""", card)
        out['callerCard'] = await page.evaluate("!!document.querySelector('#fc-card-p%%d .fcall-card')" %% S['call_post'])
        await page.evaluate("(sel) => document.querySelector(sel + ' .token-tag').click()", card)
        await page.wait_for_timeout(800)
        out['hash'] = await page.evaluate('location.hash')
        out['tokenModal'] = await page.evaluate("(() => { const m = document.getElementById('tokenCard'); return !!m && getComputedStyle(m).display !== 'none'; })()")
        out['errors'] = errs
        await b.close()
    print('@@' + json.dumps(out))
asyncio.run(main())
''' % (PORT, json.dumps(SEEDED))

B = {}
try:
    for _ in range(60):
        try:
            urllib.request.urlopen('http://127.0.0.1:%d/static/og-orcagent.png' % PORT, timeout=2); break
        except Exception:
            time.sleep(1)
    r = subprocess.run([sys.executable, '-c', DRIVER], capture_output=True, text=True, timeout=300)
    line = [l for l in r.stdout.splitlines() if l.startswith('@@')]
    B = json.loads(line[-1][2:]) if line else {}
    if not B: print(r.stdout[-1500:], r.stderr[-1500:])
finally:
    server.terminate()

print('measured:', json.dumps(B))
check('BROWSER: the whole "$Attention+" is one link', B.get('tags', [])[:1] == ['$Attention+'])
check('BROWSER: @orcagent\'s picture stands in for the call card; the marker never shows as text',
      B.get('picture') and not B.get('card') and B.get('text'))
check("BROWSER: the caller's own post still shows its call card", B.get('callerCard'))
check('BROWSER: tapping it opens the call itself, not a search for a token by name',
      B.get('hash') == '#post-p%d' % SEEDED.get('call_post', -1) and not B.get('tokenModal'))
check('BROWSER: no page errors', B and not B.get('errors'))

print('%d/%d' % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
