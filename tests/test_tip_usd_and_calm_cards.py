"""Tipping shows the dollars, Portfolio's balance card is calm, Home has no trending card.

Before:
- the tip sheet showed a SOL tip as "0.050000000 SOL" with "Total budget
  including the network fee" where the dollar value belongs -- nobody could
  see what they were sending in dollars;
- the Portfolio balance card stacked five lines of small print (estimated
  value, "portfolio equivalent", "Live Solana balance", 6-decimal SOL);
- the home feed opened with a busy Trending card (LIVE badge, token rail,
  Bullish/Bearish), which has been taken out.

Now the tip sheet converts the amount live (SOL at the current price,
refreshed while the sheet is open; USDC one to one), the receipt shows it
too, and /api/price/sol serves the price the app already keeps fresh.
"""
import json, os, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
checks = []
def check(name, cond, detail=''):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name + ((' -- %s' % detail) if detail and not cond else ''), flush=True)

PORT = 5132
ENV = dict(os.environ, DATA_DIR=tempfile.mkdtemp(), ENCRYPTION_KEY='6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
           ORCAGENT_FRONTS_GAS='0', ORCAGENT_PLATFORM_POSTS='0', ORCAGENT_TRENDING_ALERTS='0', PYTHONPATH=ROOT)

# ── the price endpoint: the app's own SOL price, or null -- never a guess ──
PRICE = r'''
import os, sys, json
sys.path.insert(0, %r)
import app_entry
d = app_entry._dashboard; c = app_entry.app.test_client()
out = []
d._sol_price_usd = 0.0
out.append(c.get('/api/price/sol', base_url='https://orcagent.fun').get_json())
d._sol_price_usd = 116.4049
r = c.get('/api/price/sol', base_url='https://orcagent.fun')
out.append(r.get_json()); out.append(r.headers.get('Cache-Control'))
print('@@' + json.dumps(out))
os._exit(0)
''' % ROOT
r = subprocess.run([sys.executable, '-c', PRICE], env=ENV, capture_output=True, text=True, timeout=180)
P = json.loads(([l[2:] for l in r.stdout.splitlines() if l.startswith('@@')] or ['[{},{},null]'])[-1])
check('/api/price/sol gives no price (null) while the app has none', P[0].get('ok') and P[0].get('sol_price_usd') is None, str(P))
check('...and the app\'s live SOL price once it has one, never cached by the browser',
      P[1].get('sol_price_usd') == 116.4049 and P[2] == 'no-store', str(P))

SEED = r'''
import os, sys, sqlite3
sys.path.insert(0, %r)
import app_entry
d = app_entry._dashboard; app = app_entry.app
from solders.keypair import Keypair
w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
r = str(Keypair().pubkey()); rid = d.get_or_create_user(r)
c = sqlite3.connect(d.DB_FILE)
for u in (uid, rid):
    c.execute('INSERT INTO tos_acceptances (user_id, version, accepted_at) VALUES (?,?,datetime())', (u, d.TOS_VERSION))
c.execute("UPDATE users SET username='tipper' WHERE id=?", (uid,))
c.execute("UPDATE users SET username='jessica' WHERE id=?", (rid,))
c.commit(); c.close()
with app.test_request_context():
    from flask import session
    session['wallet'] = w; session['csrf_token'] = 'x' * 64; session.permanent = True
    resp = app.response_class(); app.session_interface.save_session(app, session, resp)
    print('@@' + resp.headers['Set-Cookie'].split(';')[0].split('=', 1)[1] + ' ' + r)
os._exit(0)
''' % ROOT
r = subprocess.run([sys.executable, '-c', SEED], env=ENV, capture_output=True, text=True, timeout=180)
COOKIE, RECIP = ([l[2:] for l in r.stdout.splitlines() if l.startswith('@@')] or [' '])[-1].split(' ')
server = subprocess.Popen([sys.executable, '-c',
    'import app_entry as d;d._dashboard._rate_ok=lambda *a,**k:True;'
    'd.app.run(host="127.0.0.1",port=%d,debug=False,use_reloader=False,threaded=True)' % PORT],
    env=ENV, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

DRIVER = r'''
import asyncio, json, os
from playwright.async_api import async_playwright
PORT, COOKIE, RECIP = %d, %r, %r
SNAP = {'ok': True, 'total_usd': 1248.37, 'total_sol': 10.7245, 'available_to_trade_sol': 3.41529871,
        'stale': False, 'inventory_complete': True, 'valuation_complete': True,
        'sol': {'amount': 3.41529871, 'value_usd': 397.54}, 'stable': {'total_usdc': 612.2}, 'other_assets_value_usd': 238.63, 'tokens': []}
PX = {'v': 116.4}
TIPS = """[document.getElementById('tip-approx').textContent.trim(),
  (document.getElementById('tip-rate')||{}).textContent||'',
  document.getElementById('tip-send-val').textContent.trim(),
  document.getElementById('tip-send-usd').textContent.trim()]"""
async def main():
    async with async_playwright() as p:
        try:
            b = await p.chromium.launch(args=['--no-sandbox'])
        except Exception:
            b = await p.chromium.launch(args=['--no-sandbox'], executable_path=os.environ.get('CHROMIUM_PATH') or '/opt/pw-browsers/chromium')
        ctx = await b.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        await ctx.add_init_script("try{localStorage.setItem('orcagent_tips_seen','1');localStorage.setItem('orca_wizard_dismissed','1')}catch(e){}")
        await ctx.add_cookies([{'name': 'orca_s', 'value': COOKIE, 'domain': '127.0.0.1', 'path': '/'}])
        await ctx.route('**/api/portfolio/snapshot*', lambda r: r.fulfill(status=200, content_type='application/json', body=json.dumps(SNAP)))
        await ctx.route('**/api/price/sol', lambda r: r.fulfill(status=200, content_type='application/json',
                        body=json.dumps({'ok': True, 'sol_price_usd': PX['v']})))
        await ctx.route('**/api/tip', lambda r: r.fulfill(status=200, content_type='application/json',
                        body=json.dumps({'ok': True, 'tip_id': None, 'amount_sent': 0.05, 'currency': 'SOL', 'chain': 'solana', 'status': 'submitted'})))
        page = await ctx.new_page(); out = {}
        await page.goto('http://127.0.0.1:%%d/wallet' %% PORT, wait_until='load'); await page.wait_for_timeout(2500)
        out['hero'] = await page.evaluate("""(() => { const h = document.getElementById('pf-total').closest('.wlt-hero, section, div');
          const card = document.getElementById('pf-total').parentElement;
          const perf = document.getElementById('pf-performance');
          return {text: card.innerText, avail: document.getElementById('avail').textContent.trim(),
                  perfShown: getComputedStyle(perf).display !== 'none'}; })()""")
        await page.goto('http://127.0.0.1:%%d/' %% PORT, wait_until='load'); await page.wait_for_timeout(2500)
        out['home'] = await page.evaluate("""[document.querySelectorAll('.oa-th-post').length,
          [...document.scripts].some(s => /home-trending-hero/.test(s.src))]""")
        await page.goto('http://127.0.0.1:%%d/profile/%%s' %% (PORT, RECIP), wait_until='load'); await page.wait_for_timeout(1200)
        await page.evaluate('_openTip()'); await page.wait_for_timeout(500)
        await page.fill('#tip-amount', '0.05'); await page.wait_for_timeout(200)
        out['sol'] = await page.evaluate(TIPS)
        PX['v'] = 120.0
        await page.wait_for_timeout(11000)          # the price refreshes while the sheet is open
        out['sol_later'] = await page.evaluate(TIPS)
        await page.fill('#tip-amount', '0.00005'); await page.wait_for_timeout(200)
        out['tiny'] = await page.evaluate(TIPS)
        await page.evaluate("_tipSetCur('USDC')"); await page.fill('#tip-amount', '5'); await page.wait_for_timeout(200)
        out['usdc'] = await page.evaluate(TIPS)
        await page.evaluate("_tipSetCur('SOL')"); await page.fill('#tip-amount', '0.05'); await page.wait_for_timeout(200)
        await page.click('#tip-submit'); await page.wait_for_timeout(800)
        out['receipt'] = await page.evaluate("""[document.getElementById('oa-tip-receipt-amount').textContent.trim(),
          ((document.getElementById('oa-tip-receipt-usd')||{}).textContent||'').trim()]""")
        await b.close()
    print('@@' + json.dumps(out))
asyncio.run(main())
''' % (PORT, COOKIE, RECIP)

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
sol, later, tiny, usdc = B.get('sol', []), B.get('sol_later', []), B.get('tiny', []), B.get('usdc', [])
check('BROWSER: a SOL tip shows its dollar value right under the amount (0.05 SOL at $116.40 = $5.82)',
      sol[:1] == ['≈ $5.82'] and '1 SOL = $116.40' in (sol[1] if len(sol) > 1 else ''), str(sol))
check('BROWSER: ...and "You send" reads 0.05 SOL ≈ $5.82, not 0.050000000', sol[2:] == ['0.05', '≈ $5.82'], str(sol))
check('BROWSER: ...converted live: a new SOL price while the sheet is open updates it ($6.00 at $120)',
      later[:1] == ['≈ $6.00'] and later[3:] == ['≈ $6.00'] and '1 SOL = $120.00' in (later[1] if len(later) > 1 else ''), str(later))
check('BROWSER: ...a tiny tip says less than a cent instead of $0.00', tiny[:1] == ['< $0.01'], str(tiny))
check('BROWSER: a USDC tip is the same in dollars', usdc[:1] == ['= $5.00'] and usdc[2:] == ['5.00', '= $5.00'], str(usdc))
check('BROWSER: the receipt shows the dollar value too', B.get('receipt') == ['0.05 SOL', '≈ $6.00'], str(B.get('receipt')))

hero = B.get('hero', {})
text = hero.get('text', '')
check('BROWSER: Portfolio balance card is calm: total, SOL equivalent and what is available to trade',
      '1,248.37' in text and '≈ 10.7245 SOL' in text and 'Available to trade: 3.4153 SOL' in text, text)
check('BROWSER: ...without the small print it used to stack up',
      not any(s in text for s in ('Estimated value', 'portfolio equivalent', 'Live Solana balance', 'trading uses SOL'))
      and hero.get('perfShown') is False, json.dumps(hero))
check('BROWSER: Home has no trending card any more', B.get('home') == [0, False], str(B.get('home')))

print('%d/%d' % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
