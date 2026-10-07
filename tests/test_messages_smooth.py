"""Messages: switching between conversations is smooth and a sent message is
there at once, at the bottom, the way Instagram, X and WhatsApp behave.

Measured on a phone (390x844, CPU 4x slower, the server answering after
600ms), frame by frame:

- Every conversation opened on an empty "Loading..." screen until the server
  answered, also one you had just looked at.
- The thread was drawn at the top and only jumped to the newest message a
  frame or two later; the fullscreen chat layout and the small avatars beside
  incoming messages were also added a frame late.
- A sent message appeared only after two round trips (send, then reload the
  whole thread), and the send button took the keyboard away.
- When the keyboard opened, the chat was checked for "at the bottom" only
  after it had shrunk, so the newest messages slid behind the keyboard.
"""
import json, os, sqlite3, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

PORT = 5099
DATA = tempfile.mkdtemp()
ENV = dict(os.environ, DATA_DIR=DATA, ENCRYPTION_KEY='6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
           ORCAGENT_FRONTS_GAS='0', ORCAGENT_PLATFORM_POSTS='0', PYTHONPATH=ROOT)
SEED = r'''
import os, sys, sqlite3
sys.path.insert(0, %r)
import app_entry
d = app_entry._dashboard; app = app_entry.app
from solders.keypair import Keypair
w = str(Keypair().pubkey()); me = d.get_or_create_user(w)
c = sqlite3.connect(d.DB_FILE)
c.execute('INSERT INTO tos_acceptances (user_id, version, accepted_at) VALUES (?,?,datetime())', (me, d.TOS_VERSION))
c.commit()
c.close()
peers = [d.get_or_create_user(str(Keypair().pubkey())) for _ in range(3)]
c = sqlite3.connect(d.DB_FILE)
for n, pid in enumerate(peers):
    c.execute('UPDATE users SET username=? WHERE id=?', ('trader%%d' %% n, pid))
    for i in range(60):
        s, r = (me, pid) if i %% 3 else (pid, me)
        c.execute("INSERT INTO direct_messages (sender_id, receiver_id, message, created_at, is_read) VALUES (?,?,?, datetime('now', ?), 1)",
                  (s, r, 'Message %%d with trader%%d about the market, entries and exits today' %% (i, n), '-%%d minutes' %% ((60 - i) * 7)))
c.commit(); c.close()
with app.test_request_context():
    from flask import session
    session['wallet'] = w; session['csrf_token'] = 'x' * 64; session.permanent = True
    resp = app.response_class(); app.session_interface.save_session(app, session, resp)
    print('@@' + json.dumps({'cookie': resp.headers['Set-Cookie'].split(';')[0].split('=', 1)[1], 'peers': peers}))
os._exit(0)
'''.replace('json.dumps', '__import__("json").dumps') % ROOT
r = subprocess.run([sys.executable, '-c', SEED], env=ENV, capture_output=True, text=True, timeout=180)
SEEDED = json.loads(([l[2:] for l in r.stdout.splitlines() if l.startswith('@@')] or ['{}'])[-1] or '{}')
if not SEEDED: print(r.stdout[-1500:], r.stderr[-1500:])
server = subprocess.Popen([sys.executable, '-c',
    'import app_entry as d;d._dashboard._rate_ok=lambda *a,**k:True;'
    'd.app.run(host="127.0.0.1",port=%d,debug=False,use_reloader=False,threaded=True)' % PORT],
    env=ENV, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

DRIVER = r'''
import asyncio, json, os
from playwright.async_api import async_playwright
PORT, SEEDED = %d, %s
COOKIE, PEERS = SEEDED['cookie'], SEEDED['peers']
# One sample per frame while a conversation opens.
WATCH = """window.__f = []; window.__g = (window.__g || 0) + 1; (function tick(g){ if (g !== window.__g) return; const a = document.getElementById('msgs-area');
  const main = document.getElementById('msgs-main'); const app = document.getElementById('app');
  if (main && main.classList.contains('thread-open')) {
    const rows = a ? a.querySelectorAll('.msg-wrap').length : 0;
    const theirs = a ? a.querySelectorAll('.msg-wrap.theirs').length : 0;
    const av = a ? a.querySelectorAll('.msg-wrap.theirs > .oa-peer-mini-avatar').length : 0;
    __f.push({rows, gap: a ? Math.round(a.scrollHeight - a.scrollTop - a.clientHeight) : -1,
              fixed: app ? getComputedStyle(app).position === 'fixed' : false, avatarsLate: theirs - av,
              h: a ? a.clientHeight : 0, top: a ? Math.round(a.scrollTop) : 0});
  }
  if (__f.length < 400) requestAnimationFrame(() => tick(g)); })(window.__g);"""
def summary(frames):
    shown = [f for f in frames if f['rows']]
    return {'frames': len(frames), 'empty': sum(1 for f in frames if not f['rows']),
            'notAtBottom': sum(1 for f in shown if f['gap'] > 4), 'notFullscreen': sum(1 for f in frames if not f['fixed']),
            'avatarsLate': sum(1 for f in shown if f['avatarsLate'] > 0),
            'off': [(i, f['gap'], f['h'], f['top']) for i, f in enumerate(frames) if f['rows'] and (f['gap'] > 4 or i < 3)][:6]}
async def main():
    async with async_playwright() as p:
        try:
            b = await p.chromium.launch(args=['--no-sandbox'])
        except Exception:
            b = await p.chromium.launch(args=['--no-sandbox'], executable_path=os.environ.get(
                'CHROMIUM_PATH') or '/opt/pw-browsers/chromium')
        ctx = await b.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        await ctx.add_cookies([{'name': 'orca_s', 'value': COOKIE, 'domain': '127.0.0.1', 'path': '/'}])
        page = await ctx.new_page(); errs = []
        page.on('pageerror', lambda e: errs.append(str(e)[:160]))
        async def slow(route):   # a phone network: the server answers after 600ms
            await asyncio.sleep(0.6); await route.continue_()
        await page.goto('http://127.0.0.1:%%d/messages' %% PORT, wait_until='load')
        await page.wait_for_selector('.conv-row-wrap', timeout=30000)
        await page.wait_for_timeout(1200)
        await page.route('**/api/messages/**', slow)
        cdp = await ctx.new_cdp_session(page)
        await cdp.send('Emulation.setCPUThrottlingRate', {'rate': 4})
        out = {}
        async def open_peer(pid, name):
            await page.evaluate(WATCH)
            await page.evaluate("document.querySelector('.conv-row-wrap[data-peer-id=\"%%d\"] .conv-row').dispatchEvent(new MouseEvent('click', {bubbles: true}))" %% pid)
            await page.wait_for_timeout(2500)
            out[name] = summary(await page.evaluate('__f'))
        async def back():
            await page.evaluate('_backToList()'); await page.wait_for_timeout(600)
        await open_peer(PEERS[0], 'first_open'); await back()
        await open_peer(PEERS[1], 'other_open'); await back()
        await open_peer(PEERS[0], 'reopen')
        # Sending, scrolled up in the history: the message is there at once, at the bottom.
        await page.evaluate("document.getElementById('msgs-area').scrollTop = 0")
        await page.focus('#msgs-input'); await page.keyboard.type('Instant hello')
        await page.tap('#msgs-send')
        out['send'] = await page.evaluate("""new Promise(res => requestAnimationFrame(() => setTimeout(() => {
            const a = document.getElementById('msgs-area'); const rows = [...a.querySelectorAll('.msg-wrap')];
            const last = rows[rows.length - 1];
            res({shown: !!last && last.textContent.includes('Instant hello'), gap: Math.round(a.scrollHeight - a.scrollTop - a.clientHeight),
                 focused: document.activeElement && document.activeElement.id === 'msgs-input',
                 empty: document.getElementById('msgs-input').value === ''}); }, 120)))""")
        await page.wait_for_timeout(3500)
        out['after_send'] = await page.evaluate("""(() => { const a = document.getElementById('msgs-area');
            return {copies: [...a.querySelectorAll('.msg-wrap')].filter(r => r.textContent.includes('Instant hello')).length,
                    saved: !!a.querySelector('.msg-wrap.mine[data-mid]:not([data-mid^="tmp"])'),
                    pending: a.querySelectorAll('.msg-wrap.pending').length,
                    gap: Math.round(a.scrollHeight - a.scrollTop - a.clientHeight)}; })()""")
        # Opening the keyboard keeps the newest message in view.
        await page.focus('#msgs-input')
        await page.set_viewport_size({'width': 390, 'height': 500})
        await page.wait_for_timeout(800)
        out['keyboard'] = await page.evaluate("(() => { const a = document.getElementById('msgs-area'); return Math.round(a.scrollHeight - a.scrollTop - a.clientHeight); })()")
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
first, other, again = B.get('first_open', {}), B.get('other_open', {}), B.get('reopen', {})
for name, s in (('opening a conversation', first), ('switching to another conversation', other)):
    check('BROWSER: %s shows it at the newest message from the first frame (frames elsewhere: %s)'
          % (name, s.get('notAtBottom')), s and s['notAtBottom'] == 0)
    check('BROWSER: ...fullscreen from the first frame, avatars drawn with the messages (late frames: %s/%s)'
          % (s.get('notFullscreen'), s.get('avatarsLate')), s and s['notFullscreen'] == 0 and s['avatarsLate'] == 0)
check('BROWSER: going back to a conversation shows it at once, no empty Loading screen (empty frames: %s)'
      % again.get('empty'), again and again['empty'] == 0 and again['notAtBottom'] == 0)
snd = B.get('send', {})
check('BROWSER: a sent message is at the bottom at once, before the server answers', snd.get('shown') and snd.get('gap', 99) <= 4)
check('BROWSER: ...the field is cleared and keeps the keyboard', snd.get('empty') and snd.get('focused'))
aft = B.get('after_send', {})
check('BROWSER: once saved it is there exactly once, still at the bottom',
      aft.get('copies') == 1 and aft.get('saved') and aft.get('pending') == 0 and aft.get('gap', 99) <= 4)
check('BROWSER: opening the keyboard keeps the newest message in view (gap %s)' % B.get('keyboard'),
      B.get('keyboard') is not None and B['keyboard'] <= 4)
check('BROWSER: no page errors', B and not B.get('errors'))

print('%d/%d' % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
