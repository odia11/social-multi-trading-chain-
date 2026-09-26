"""The Trending card can be shared on X, and unfurls as that card.

- the card has a Share button (anyone, signed in or not): Post on X /
  Copy link / the phone's own share sheet;
- the link /trending/<chain>/<token> carries a large-image X card with the
  token's live numbers, and its image /api/trending-card/<chain>/<token>.png
  is the Trending card drawn at 1200x630;
- opening the link lands on the card in the app (or on the token in Live
  Market once it no longer trends);
- the image is crawlable (robots.txt allows it) and bad input is refused.
"""
import io, math, os, re, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_TRENDING_ALERTS': '0'})
import app_entry  # noqa: E402
import trending_hero as th  # noqa: E402
import trending_share as ts  # noqa: E402
from flask import jsonify  # noqa: E402
from PIL import Image  # noqa: E402
d = app_entry._dashboard
app = app_entry.app

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

M = 'SJPmint111111111111111111111111111111pump'
TOK = {'mint': M, 'symbol': 'SJP', 'name': 'Super Jean Phil', 'chain': 'solana', 'pair_address': 'Pair' + M[:30],
       'price_usd': 0.000107, 'price_change_24h': 33.1, 'volume_24h': 1_990_000, 'liquidity_usd': 90_000,
       'market_cap': 1_800_000, 'buys_24h': 35425, 'sells_24h': 20623, 'image_url': ''}
scanner = [TOK]
d._get_scanner_cached = lambda: scanner
d._scanner_get_safety = lambda *a, **k: {'ok': True}
d._scanner_token_passes_scam_filter = lambda t, s: True
th._surging = lambda _d: {}
d._dex_get = lambda *a, **k: None            # no network
closes = [0.0001 + 0.000005 * math.sin(i / 4) for i in range(40)] + [0.000107]
app.view_functions['api_chart'] = lambda mint: jsonify({'candles': [{'c': c} for c in closes]})

BASE = 'https://orcagent.fun'
H = {'User-Agent': 'Twitterbot/1.0'}
c = app.test_client()
def fresh():
    th._state['at'] = 0.0
    ts._cache.clear()
def meta(html, name):
    m = re.search(r'<meta (?:name|property)="%s" content="([^"]*)">' % re.escape(name), html)
    return m.group(1) if m else None

# ── the shared link while the token is trending ──
fresh()
r = c.get(f'/trending/solana/{M}?s=1', base_url=BASE, headers=H)
page = r.get_data(as_text=True)
check('the share link opens', r.status_code == 200)
check('...as a large-image X card', meta(page, 'twitter:card') == 'summary_large_image')
check('...titled with the token and its move',
      meta(page, 'twitter:title') == '$SJP is trending on Solana 🔥 +33.1% in 24h' and meta(page, 'og:title') == meta(page, 'twitter:title'))
check('...described with volume and buy pressure',
      '$1.99M volume' in meta(page, 'twitter:description') and '63% buy pressure' in meta(page, 'twitter:description'))
img_url = meta(page, 'twitter:image')
check('...with the card image', img_url and img_url.startswith(f'https://orcagent.fun/api/trending-card/solana/{M}.png')
      and meta(page, 'og:image') == img_url and meta(page, 'og:image:width') == '1200')
check('...tags at the top of the page', page.find('twitter:image') < 4000)
check('people who open it land on the Trending card in the app', 'location.replace("/?trending=1#trending")' in page)

r = c.get(img_url.replace('https://orcagent.fun', '').replace('&amp;', '&'), base_url=BASE, headers=H)
check('the card image is a PNG', r.status_code == 200 and r.mimetype == 'image/png')
im = Image.open(io.BytesIO(r.data)).convert('RGB')
check("...in X's 1200x630 frame", im.size == (1200, 630))
near = lambda p, t, tol=40: all(abs(a - b) <= tol for a, b in zip(p, t))
check('...drawn like the Trending card: gold Trade button', near(im.getpixel((720, 536)), ts.GOLD2))
check('...green buy / red sell pressure bar', near(im.getpixel((700, 380)), ts.GREEN) and near(im.getpixel((1110, 380)), ts.RED))
check('...and the gold OrcAgent mark', near(im.getpixel((56, 50)), ts.GOLD))
check('...crawlable (no noindex)', 'noindex' not in (r.headers.get('X-Robots-Tag') or ''))
robots = c.get('/robots.txt', base_url=BASE).get_data(as_text=True)
check('robots.txt lets X fetch the image', 'Allow: /api/trending-card/' in robots
      and robots.index('Allow: /api/trending-card/') < robots.index('Disallow: /api/'))

# ── after it stops trending ──
scanner[:] = []
fresh()
page = c.get(f'/trending/solana/{M}', base_url=BASE, headers=H).get_data(as_text=True)
check('a token that no longer trends (and no live data) still unfurls, with the OrcAgent preview',
      meta(page, 'twitter:image') == 'https://orcagent.fun/static/og-orcagent.png')
check('...and opens the token on Live Market', f'location.replace("/live-market?mint={M}")' in page)
r = c.get(f'/api/trending-card/solana/{M}.png', base_url=BASE, headers=H)
check('...its image falls back to the OrcAgent preview', r.status_code == 302 and r.headers['Location'].endswith('/static/og-orcagent.png'))

# ── bad input ──
check('an unknown chain is refused', c.get(f'/trending/dogechain/{M}', base_url=BASE).status_code == 404)
check('a malformed token is refused', c.get('/trending/solana/<script>', base_url=BASE).status_code == 404
      and c.get('/api/trending-card/base/0x123.png', base_url=BASE).status_code == 404)

# ── the button ──
js = open(os.path.join(os.path.dirname(__file__), '..', 'static', 'home-trending-hero.js')).read()
check('the card has a Share button', 'oa-th-act oa-th-share' in js)
check('...Post on X uses the share link', "https://x.com/intent/post?text=" in js and "'/trending/'+encodeURIComponent(t.chain)" in js)
check('...Copy link and the phone share sheet', 'oa-th-share-copy' in js and 'navigator.share(' in js)
check('...anyone may share (checked before the sign-in gate)',
      js.index("if(b.classList.contains('oa-th-share')){openShare(b);return;}") < js.index("checkGuest()"))
css = open(os.path.join(os.path.dirname(__file__), '..', 'static', 'home-trending-hero.css')).read()
check('...icon-only on phones so the row fits', '.oa-th-share span{display:none}' in css)
raise SystemExit(0 if all(checks) else 1)
