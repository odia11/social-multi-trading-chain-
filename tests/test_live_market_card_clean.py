"""The Live Market token card on a phone is tidy and clear, in dark and light.

It was not:
- icons were attached to the stat tiles by position, and the price and the
  24h change counted as positions, so only Liquidity and Market cap had one
  (the wrong ones) and the four tiles' text did not line up;
- Buy was an outline and Sell the filled gold button -- the other way round;
- the SOL badge (every Live Market token is Solana) was cut off by Profile;
- the top price on the chart axis sat under the timeframe buttons;
- "5.3K txns" stood in its own empty bordered box.
"""
import json, os, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
checks = []
def check(name, cond, detail=''):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name + ((' -- %s' % detail) if detail and not cond else ''), flush=True)

PORT = 5103
ENV = dict(os.environ, DATA_DIR=tempfile.mkdtemp(), ENCRYPTION_KEY='6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
           ORCAGENT_FRONTS_GAS='0', ORCAGENT_PLATFORM_POSTS='0', PYTHONPATH=ROOT)
server = subprocess.Popen([sys.executable, '-c',
    'import app_entry as d;d._dashboard._rate_ok=lambda *a,**k:True;'
    'd.app.run(host="127.0.0.1",port=%d,debug=False,use_reloader=False,threaded=True)' % PORT],
    env=ENV, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

DRIVER = r'''
import asyncio, json, os, time, random
from playwright.async_api import async_playwright
PORT = %d
now = int(time.time() * 1000)
TOK = {'mint': '7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr', 'symbol': 'POPCAT', 'name': 'Popcat', 'chain': 'solana',
       'dex_id': 'raydium', 'pair_address': 'FRhB8L7Y9Qq41qZXYLtC2nw8An1RJfLLxRF2x9RwLLMo', 'image_url': '',
       'price_usd': 0.000207, 'market_cap': 207e6, 'liquidity_usd': 8.28e6, 'volume_24h': 22.77e6,
       'buys_24h': 3200, 'sells_24h': 2100, 'price_change_24h': 46.8, 'pair_created_at': now - 5 * 86400000,
       'verified_socials': True, 'score': 4}
def candles():
    r = random.Random(1); t0 = int(time.time()) // 300 * 300 - 79 * 300; v = 0.00015; out = []
    for i in range(80):
        o = v; v *= 1 + r.uniform(-0.03, 0.04); out.append({'t': t0 + i * 300, 'o': o, 'h': max(o, v) * 1.01, 'l': min(o, v) * .99, 'c': v, 'v': r.uniform(1e3, 9e3)})
    return out
PROBE = """(() => { const c = document.querySelector('.pt-card'); const R = e => e.getBoundingClientRect();
  const vis = e => { if (!e) return false; const s = getComputedStyle(e), r = R(e); return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0; };
  const tiles = [...c.querySelectorAll('.pt-stat-row')];
  const icons = tiles.filter(t => { const s = getComputedStyle(t, '::before'); return s.content !== 'none' && s.display !== 'none' && s.backgroundImage !== 'none'; }).length;
  const lblX = tiles.map(t => Math.round(R(t.querySelector('.pt-stat-lbl')).left - R(t).left));
  const hts = tiles.map(t => Math.round(R(t).height));
  const buy = getComputedStyle(c.querySelector('.pt-buy-btn')), sell = getComputedStyle(c.querySelector('.pt-sell-btn'));
  const badge = c.querySelector('.pt-chain-badge'), cr = R(c);
  const tfs = R(c.querySelector('.pt-chart-tfs'));
  const labels = [...c.querySelectorAll('.pt-chart-svg > text')].filter(vis).map(R);
  const overTfs = labels.filter(l => l.top < tfs.bottom && l.right > tfs.left).length;
  const ft = c.querySelector('.pt-card-ft'), fts = getComputedStyle(ft);
  const out = [...c.querySelectorAll('*')].filter(e => vis(e) && R(e).right > cr.right + 1 && !e.closest('.pt-chart-wrap')).length;
  return {tiles: tiles.length, icons, lblX, hts,
          buyFilled: buy.backgroundImage !== 'none' || (buy.backgroundColor !== 'rgba(0, 0, 0, 0)' && buy.backgroundColor !== 'transparent'),
          sellOutline: sell.backgroundImage === 'none' && (sell.backgroundColor === 'rgba(0, 0, 0, 0)' || sell.backgroundColor === 'transparent'),
          badgeClipped: vis(badge) && R(badge).right > R(c.querySelector('.pt-card-hd-right')).left,
          overTfs, ftBox: fts.borderTopWidth !== '0px' || (fts.backgroundColor !== 'rgba(0, 0, 0, 0)' && fts.backgroundColor !== 'transparent'),
          spill: out, ox: document.scrollingElement.scrollWidth - innerWidth}; })()"""
async def main():
    async with async_playwright() as p:
        try:
            b = await p.chromium.launch(args=['--no-sandbox'])
        except Exception:
            b = await p.chromium.launch(args=['--no-sandbox'], executable_path=os.environ.get('CHROMIUM_PATH') or '/opt/pw-browsers/chromium')
        out = {}
        for theme in ('dark', 'light'):
            for w, h in ((390, 844), (360, 740)):
                ctx = await b.new_context(viewport={'width': w, 'height': h}, is_mobile=True, has_touch=True)
                await ctx.add_init_script("try{localStorage.setItem('oa_theme','%%s')}catch(e){}" %% theme)
                await ctx.add_cookies([{'name': 'oa_theme', 'value': theme, 'domain': '127.0.0.1', 'path': '/'}])
                await ctx.route('**/api/market/scanner*', lambda r: r.fulfill(status=200, content_type='application/json',
                                body=json.dumps({'ok': True, 'tokens': [TOK], 'counts': {'trending': 1}})))
                await ctx.route('**/api/chart/**', lambda r: r.fulfill(status=200, content_type='application/json',
                                body=json.dumps({'ok': True, 'candles': candles(), 'source': 'test'})))
                page = await ctx.new_page()
                await page.goto('http://127.0.0.1:%%d/live-market' %% PORT, wait_until='load')
                await page.wait_for_selector('.pt-card .pt-buy-btn', timeout=30000)
                await page.wait_for_timeout(1500)
                out['%%s_%%d' %% (theme, w)] = await page.evaluate(PROBE)
                await ctx.close()
        await b.close()
    print('@@' + json.dumps(out))
asyncio.run(main())
''' % PORT

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
for key in ('dark_390', 'light_390', 'dark_360', 'light_360'):
    m = B.get(key, {})
    check('%s: four stat tiles, no icons, text lined up, same height' % key,
          m.get('tiles') == 4 and m.get('icons') == 0 and len(set(m.get('lblX', [0, 1]))) == 1 and max(m.get('hts', [0])) - min(m.get('hts', [99])) <= 1, str(m))
    check('%s: Buy is the filled main button, Sell an outline' % key, m.get('buyFilled') and m.get('sellOutline'), str(m))
    check('%s: nothing cut off in the header, no axis price under the timeframe buttons' % key,
          not m.get('badgeClipped') and m.get('overTfs') == 0, str(m))
    check('%s: the transactions line has no empty box, nothing sticks out of the card' % key,
          m.get('ftBox') is False and m.get('spill') == 0 and m.get('ox', 1) <= 0, str(m))

print('%d/%d' % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
