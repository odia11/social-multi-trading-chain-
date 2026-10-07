"""Turning a phone or tablet never leaves a broken page.

Home is built once, for the width it loaded at: the mobile dashboard up to
767px, the desktop dashboard from 1025px, a plain layout in between. Each
build brings its own scripts and styles. Turning a phone to landscape moved
the width past those lines while the page kept the mobile build -- its blocks
lost their mobile-only styles and showed as bare blue links and icons the
size of the screen. Now:

- Home is built again when the width crosses one of those lines (and waits
  while someone is typing), and mobile blocks are never shown unstyled;
- the mobile Home and its styles use one line (767px), so an iPad in portrait
  (768px) no longer gets half of each;
- Live Market fits an iPad in landscape (901-1219px): the three columns
  needed 1220px, so the token panel was pushed off the screen; the filters
  now sit behind the same "Filters" drawer the phone uses.
"""
import json, os, re, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()

NAV = read('static', 'navbar.js')
check('Home is built again when the width crosses 767px or 1025px',
      "matchMedia('(max-width:767px)')" in NAV and "matchMedia('(min-width:1025px)')" in NAV
      and 'location.reload()' in NAV)
check('the mobile Home and its styles switch at the same width',
      "matchMedia('(max-width:767px)').matches) return;" in read('static', 'home-mobile.js')
      and "if(here!=='/'||!window.matchMedia('(max-width:767px)').matches)return;" in NAV
      and read('static', 'home-mobile.css').count('@media(max-width:767px){') >= 1
      and '@media(max-width:768px){' not in read('static', 'home-mobile.css')
      and 'media="(max-width:767px)"' in read('app_performance.py'))
check('Live Market has a layout for tablet landscape',
      '@media (min-width: 901px) and (max-width: 1219px)' in read('templates', 'live_market_pro.html'))

# ── in a real browser ─────────────────────────────────────────────────────
PORT = 5098
DATA = tempfile.mkdtemp()
ENV = dict(os.environ, DATA_DIR=DATA, ENCRYPTION_KEY='6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
           ORCAGENT_FRONTS_GAS='0', ORCAGENT_PLATFORM_POSTS='0', PYTHONPATH=ROOT)
SEED = r'''
import os, sys, sqlite3
sys.path.insert(0, %r)
import app_entry
d = app_entry._dashboard; app = app_entry.app
from solders.keypair import Keypair
w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
c = sqlite3.connect(d.DB_FILE)
c.execute('INSERT INTO tos_acceptances (user_id, version, accepted_at) VALUES (?,?,datetime())', (uid, d.TOS_VERSION))
for i in range(6):
    c.execute("INSERT INTO feed_posts (wallet, content) VALUES (?,?)", (w, 'Post %%d about the market' %% i))
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
import asyncio, json, os
from playwright.async_api import async_playwright
PORT, COOKIE = %d, %r
# What a broken Home looks like: mobile blocks on screen at a width they have
# no styles for, icons the size of the screen, links in browser-default blue.
LOOK = """(() => {
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
                     return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden'; };
  const mobile = [...document.querySelectorAll('.oa-m-hero,.oa-m-bot,.oa-m-portfolio,.oa-m-shortcuts,.oa-m-opps')].filter(vis).length;
  const big = [...document.querySelectorAll('svg')].filter(s => vis(s) && !s.closest('[class*=chart],[class*=spark],[class*=-art]')
      && s.getBoundingClientRect().width > 140 && s.getBoundingClientRect().height > 140).length;
  const raw = [...document.querySelectorAll('a')].filter(a => vis(a) && getComputedStyle(a).color === 'rgb(0, 0, 238)').length;
  return {mobile, big, raw, ox: document.scrollingElement.scrollWidth - innerWidth, w: innerWidth, mark: !!window.__same};
})()"""
async def turn(page, w, h):
    await page.evaluate('window.__same = 1')
    await page.set_viewport_size({'width': w, 'height': h})
    await page.wait_for_timeout(2500)
    await page.wait_for_load_state('load')
    await page.wait_for_timeout(1500)
    return await page.evaluate(LOOK)
async def main():
    async with async_playwright() as p:
        try:
            b = await p.chromium.launch(args=['--no-sandbox'])
        except Exception:
            b = await p.chromium.launch(args=['--no-sandbox'], executable_path=os.environ.get(
                'CHROMIUM_PATH') or '/opt/pw-browsers/chromium')
        out = {}
        async def ctx_for(w, h):
            ctx = await b.new_context(viewport={'width': w, 'height': h})
            await ctx.add_init_script("try{localStorage.setItem('orcagent_tips_seen','1');localStorage.setItem('orca_wizard_dismissed','1')}catch(e){}")
            await ctx.add_cookies([{'name': 'orca_s', 'value': COOKIE, 'domain': '127.0.0.1', 'path': '/'}])
            return ctx
        # A phone, turned to landscape and back.
        ctx = await ctx_for(390, 844); page = await ctx.new_page(); errs = []
        page.on('pageerror', lambda e: errs.append(str(e)[:160]))
        await page.goto('http://127.0.0.1:%%d/' %% PORT, wait_until='load'); await page.wait_for_timeout(2500)
        out['phone'] = await page.evaluate(LOOK)
        out['phone_landscape'] = await turn(page, 844, 390)
        out['phone_back'] = await turn(page, 390, 844)
        # A typed reply is not thrown away by turning the phone.
        await page.evaluate("""(() => { const t = document.createElement('textarea'); t.id = '__draft';
                               document.body.appendChild(t); t.value = 'half a sentence'; t.focus(); window.__same = 1; })()""")
        await page.set_viewport_size({'width': 844, 'height': 390}); await page.wait_for_timeout(1500)
        out['typing_kept'] = await page.evaluate("!!window.__same && document.getElementById('__draft').value")
        await ctx.close()
        # An iPad turned within the plain layout keeps the page; into desktop it rebuilds.
        ctx = await ctx_for(768, 1024); page = await ctx.new_page()
        page.on('pageerror', lambda e: errs.append(str(e)[:160]))
        await page.goto('http://127.0.0.1:%%d/' %% PORT, wait_until='load'); await page.wait_for_timeout(2500)
        out['ipad'] = await page.evaluate(LOOK)
        out['ipad_landscape'] = await turn(page, 1024, 768)
        out['ipad_pro_landscape'] = await turn(page, 1366, 1024)
        await ctx.close()
        # Live Market on a tablet in landscape and on a laptop.
        for w, h in ((1024, 768), (1180, 820), (1280, 800)):
            ctx = await ctx_for(w, h); page = await ctx.new_page()
            await page.goto('http://127.0.0.1:%%d/live-market' %% PORT, wait_until='load'); await page.wait_for_timeout(2000)
            out['lm%%d' %% w] = await page.evaluate("""(() => { const r = s => { const e = document.querySelector(s);
                const b = e.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.right), getComputedStyle(e).display]; };
                return {ox: document.scrollingElement.scrollWidth - innerWidth, w: innerWidth,
                        left: r('.pt-left'), right: r('.pt-right'), btn: r('#pt-mobile-filters-btn')}; })()""")
            if w == 1024:
                try:
                    await page.click('#pt-mobile-filters-btn', timeout=3000); await page.wait_for_timeout(400)
                except Exception:
                    pass   # no button on screen: the drawer check below fails
                out['lm_drawer'] = await page.evaluate("""(() => { const b = document.querySelector('.pt-left').getBoundingClientRect();
                    return {open: b.width > 200 && b.left >= 0 && b.right <= innerWidth, scrim: document.getElementById('pt-scrim').classList.contains('show')}; })()""")
            await ctx.close()
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

print('measured:', json.dumps(B))
clean = lambda s: s and s['mobile'] == 0 and s['big'] == 0 and s['raw'] == 0 and s['ox'] <= 0
ph, pl, pb = B.get('phone', {}), B.get('phone_landscape', {}), B.get('phone_back', {})
check('BROWSER: a phone shows the mobile Home', ph.get('mobile', 0) >= 1 and ph.get('ox', 1) <= 0)
check('BROWSER: turned to landscape, Home is built again with no mobile blocks, giant icons or bare links',
      pl and not pl['mark'] and clean(pl))
check('BROWSER: turned back, the mobile Home is back', pb and not pb['mark'] and pb['mobile'] >= 1 and pb['big'] == 0)
check('BROWSER: turning the phone while typing keeps what was typed', B.get('typing_kept') == 'half a sentence')
ip, il, ipp = B.get('ipad', {}), B.get('ipad_landscape', {}), B.get('ipad_pro_landscape', {})
check('BROWSER: an iPad in portrait (768px) shows a clean Home', clean(ip))
check('BROWSER: turned to landscape within the same layout, the page is kept and stays clean', il and il['mark'] and clean(il))
check('BROWSER: turned into the desktop width, Home is built again and stays clean', ipp and not ipp['mark'] and clean(ipp))
for w in (1024, 1180):
    lm = B.get('lm%d' % w, {})
    check('BROWSER: Live Market at %dpx fits: no sideways scroll, token panel on screen, filters behind a button' % w,
          lm and lm['ox'] <= 0 and lm['right'][1] <= lm['w'] and lm['left'][2] == 'none' and lm['btn'][2] == 'flex')
check('BROWSER: ...and the Filters drawer opens on screen', B.get('lm_drawer', {}).get('open') and B['lm_drawer'].get('scrim'))
lm = B.get('lm1280', {})
check('BROWSER: a laptop (1280px) keeps the three columns', lm and lm['ox'] <= 0 and lm['left'][2] == 'flex' and lm['btn'][2] == 'none')
check('BROWSER: no page errors', B and not B.get('errors'))

print('%d/%d' % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
