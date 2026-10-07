"""Scrolling the Home feed up and down does not catch or jump.

Measured on a 200-post feed (a third with pictures), scrolling down to the
end and back up, CPU slowed 4x:

- Posts more than 5000px away were torn down to a placeholder and rebuilt
  when scrolled back within range. Rebuilding while scrolling up was itself
  the stutter: 55-62 frames over 50ms on the way up (now 0-4). A rebuilt card
  also came back shorter until its picture loaded again, and Safari has no
  scroll anchoring, so the posts being read jumped: 58 layout shifts, total
  9.8 (now none). content-visibility:auto already skips off-screen cards.
- The next page (40 posts) was inserted in one go when 600px from the end:
  a 290-380ms freeze each time. It is now fetched ~3 screens ahead and added
  four cards per frame (longest task ~100ms at 4x).
- Two observers re-queried the whole document on every DOM change.
- Feed pictures decoded on the main thread during scrolling.
"""
import json, os, re, sqlite3, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()

JS = read('static', 'dashboard.js')
check('no feed card is torn down and rebuilt while scrolling',
      '_devirtualizeCard' not in JS and '_revirtualizeCard' not in JS and '_virtObserver' not in JS)
check('the next page is fetched well ahead of the end of the feed',
      re.search(r'var _FEED_PREFETCH_PX = (\d+);', JS)
      and int(re.search(r'var _FEED_PREFETCH_PX = (\d+);', JS).group(1)) >= 2000
      and 'distanceToBottom < _FEED_PREFETCH_PX' in JS)
check('...and added a few cards per frame, stopping if the feed is rebuilt meanwhile',
      'function _appendFeedCards(el, items, gen)' in JS and 'requestAnimationFrame(step)' in JS
      and 'gen !== _feedRenderGen' in JS and 'await renderHomeFeed(data.items)' in JS)
check('feed pictures decode off the main thread and keep their shape once known',
      'loading="lazy" decoding="async" onload="_fcImgLoaded(this)"' in JS
      and "aspect-ratio:'+_feedImgRatio[e.image_url]" in JS)
CALLS = read('static', 'feed-calls.js'); STC = read('static', 'shared-trade-card-v2.js')
check('call sparklines are looked for only in what was just added',
      'mutationObserver(function(){ watchSparks(feed); })' not in CALLS and 'm.addedNodes.forEach' in CALLS)
check('trade cards are hydrated only in what was just added',
      'requestAnimationFrame(function(){hydrateAll(document)})' not in STC and 'pendingRoots' in STC)

# ── in a real browser, the way Safari scrolls (no scroll anchoring) ───────
PORT = 5097
DATA = tempfile.mkdtemp()
ENV = dict(os.environ, DATA_DIR=DATA, ENCRYPTION_KEY='6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
           ORCAGENT_FRONTS_GAS='0', PYTHONPATH=ROOT)
SEED = r'''
import os, sys, sqlite3, random
sys.path.insert(0, %r)
import app_entry
d = app_entry._dashboard; app = app_entry.app
from solders.keypair import Keypair
w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
others = [str(Keypair().pubkey()) for _ in range(12)]; [d.get_or_create_user(o) for o in others]
c = sqlite3.connect(d.DB_FILE)
c.execute('INSERT INTO tos_acceptances (user_id, version, accepted_at) VALUES (?,?,datetime())', (uid, d.TOS_VERSION))
for i in range(120):
    c.execute("INSERT INTO feed_posts (wallet, content, image_url, created_at) VALUES (?,?,?, datetime('now', ?))",
              (random.choice(others), 'Post %%d about the market today, with a few words more' %% i,
               ('/static/og-orcagent.png?n=%%d' %% i) if i %% 3 == 0 else None, '-%%d seconds' %% (i * 600)))
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
    'import app_entry as d;d.app.run(host="127.0.0.1",port=%d,debug=False,use_reloader=False,threaded=True)' % PORT],
    env=ENV, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

DRIVER = r'''
import asyncio, json, os
from playwright.async_api import async_playwright
PORT, COOKIE = %d, %r
WATCH = r"""
window.__t = {rebuilt: 0, perBatch: [], shift: 0, shifts: 0};
new PerformanceObserver(l => l.getEntries().forEach(e => { __t.shift += e.value; __t.shifts++; }))
  .observe({type: 'layout-shift'});
new MutationObserver(ms => {
  let added = 0;
  ms.forEach(m => {
    // A card emptied or refilled in place = torn down / rebuilt.
    if (m.target.classList && m.target.classList.contains('fc-card') &&
        (m.removedNodes.length > 1 || m.addedNodes.length > 1)) __t.rebuilt++;
    if (m.target.id === 'center-feed')
      m.addedNodes.forEach(n => { if (n.classList && n.classList.contains('fc-card')) added++; });
  });
  if (added) __t.perBatch.push(added);
}).observe(document.getElementById('center-feed'), {childList: true, subtree: true});
"""
async def main():
    async with async_playwright() as p:
        try:
            b = await p.chromium.launch(args=['--no-sandbox'])
        except Exception:
            b = await p.chromium.launch(args=['--no-sandbox'], executable_path=os.environ.get(
                'CHROMIUM_PATH') or '/opt/pw-browsers/chromium')
        ctx = await b.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        await ctx.add_init_script("try{localStorage.setItem('orcagent_tips_seen','1');localStorage.setItem('orca_wizard_dismissed','1')}catch(e){}")
        # Safari has no scroll anchoring: anything above the viewport that
        # changes height moves what is being read.
        await ctx.add_init_script("document.addEventListener('DOMContentLoaded',()=>{const s=document.createElement('style');s.textContent='*{overflow-anchor:none!important}';document.head.appendChild(s)})")
        await ctx.add_cookies([{'name': 'orca_s', 'value': COOKIE, 'domain': '127.0.0.1', 'path': '/'}])
        page = await ctx.new_page(); errs = []
        page.on('pageerror', lambda e: errs.append(str(e)[:160]))
        await page.goto('http://127.0.0.1:%%d/' %% PORT, wait_until='load')
        await page.wait_for_selector('.fc-card', timeout=30000)
        await page.wait_for_timeout(1500)
        await page.evaluate(WATCH)
        cdp = await ctx.new_cdp_session(page)
        out = {}
        for i in range(40):   # down to the end, loading every page on the way
            await cdp.send('Input.synthesizeScrollGesture', {'x': 195, 'y': 400, 'yDistance': -1500, 'speed': 4000, 'gestureSourceType': 'mouse'})
        await page.wait_for_timeout(1200)
        out['down'] = await page.evaluate("({cards: document.querySelectorAll('.fc-card').length, y: Math.round(scrollY), perBatch: __t.perBatch, rebuilt: __t.rebuilt})")
        await page.evaluate("__t.shift = 0; __t.shifts = 0; __t.rebuilt = 0")
        for i in range(40):   # and all the way back up
            await cdp.send('Input.synthesizeScrollGesture', {'x': 195, 'y': 400, 'yDistance': 1500, 'speed': 4000, 'gestureSourceType': 'mouse'})
        await page.wait_for_timeout(800)
        out['up'] = await page.evaluate("({y: Math.round(scrollY), shift: __t.shift, shifts: __t.shifts, rebuilt: __t.rebuilt})")
        out['errors'] = errs
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
    r = subprocess.run([sys.executable, '-c', DRIVER], capture_output=True, text=True, timeout=300)
    line = [l for l in r.stdout.splitlines() if l.startswith('@@')]
    B = json.loads(line[-1][2:]) if line else {}
    if not B: print(r.stdout[-1500:], r.stderr[-1500:])
finally:
    server.terminate()

down, up = B.get('down', {}), B.get('up', {})
print('measured:', json.dumps(B))
check('BROWSER: scrolling down loads every page of the feed (120 posts)',
      down.get('cards') == 120 and down.get('y', 0) > 15000)
check('BROWSER: each next page goes in at most four cards per frame (it was 40 at once)',
      len(down.get('perBatch', [])) >= 20 and max(down.get('perBatch') or [99]) <= 4)
check('BROWSER: no card is torn down or rebuilt, scrolling either way',
      down.get('rebuilt') == 0 and up.get('rebuilt') == 0)
check('BROWSER: back at the top without the posts jumping on the way up (layout shift %.3f)'
      % up.get('shift', 99), up.get('y') == 0 and up.get('shift', 99) < 0.05)
check('BROWSER: no page errors', B and not B.get('errors'))

print('%d/%d' % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
