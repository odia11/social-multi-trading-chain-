"""Sharing a token post to X shows the app's token card as the preview.

/post/p<id> for a __CHART__ post advertises /api/trade-card/p<id>.png as
its twitter:image / og:image; that PNG is now the same token card the app
shows (share_token_card.py): symbol, name, DEX, chain, price, 24h change,
sparkline, 24h volume / liquidity / market cap / FDV, buys vs sells,
5m/1h/6h/24h changes, pair and View Token -- in X's 1200x630 frame.
"""
import io, json, os, sqlite3, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_TRENDING_ALERTS': '0'})
import app_entry  # noqa: E402
import share_token_card as st  # noqa: E402
from PIL import Image  # noqa: E402
d = app_entry._dashboard
app = app_entry.app

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

# No network in tests: the live refresh and remote images are skipped.
d._dex_get = lambda *a, **k: None
fetched = []
d._safe_external_image_url = lambda url: fetched.append(url) or False

CHART = {'symbol': 'AI', 'name': 'Attention Inu', 'chain': 'solana', 'dexId': 'pumpswap',
         'mint': 'AiMint1111111111111111111111111111111pump', 'pairAddress': '8iXGs3rQ7dK2mN5pL1vW9xY4zT6uR3Cg92',
         'price': 0.0002623, 'chg5m': 77.03, 'chg1h': 61.56, 'chg6h': 61.56, 'chg24h': 264.0,
         'vol24h': 826800, 'liq': 53100, 'marketCap': 170845, 'fdv': 170845, 'buys': 5161, 'sells': 3778,
         'banner': 'https://cdn.example/banner.png', 'image': 'https://cdn.example/logo.png'}
conn = sqlite3.connect(d.DB_FILE)
w = 'Cdn8WftaYycdudV9yeeQPY1A1Tgo1bMa9eV4Tv9SeAM9'
d.get_or_create_user(w)
cur = conn.execute('INSERT INTO feed_posts (wallet, content, created_at) VALUES (?,?,?)',
                   (w, 'Attention Inu 🐶\n__CHART__' + json.dumps(CHART), '2026-09-25 20:00:00'))
chart_id = 'p%d' % cur.lastrowid
cur = conn.execute('INSERT INTO feed_posts (wallet, content, created_at) VALUES (?,?,?)',
                   (w, 'just text', '2026-09-25 20:01:00'))
text_id = 'p%d' % cur.lastrowid
conn.commit(); conn.close()

# ── pure pieces ──
card = st.card_data(d, CHART, live=False)
check('card data comes from the post', card['symbol'] == 'AI' and card['vol'] == 826800 and card['buys'] == 5161)
check('volume/liquidity read like the app ($826.8K)', st.fmt_compact(826800) == '$826.8K' and st.fmt_compact(53100) == '$53.1K')
check('market cap/FDV read like the app ($170,845)', st.fmt_money(170845) == '$170,845')
check('price reads like the app', st.fmt_price(0.0002623) == '$0.0002623')
pts = st.spark_points(0.0002623, 264.0, 61.56, 61.56, 77.03)
check('sparkline goes through real prices (-24h … now)',
      len(pts) == 5 and abs(pts[0] - 0.0002623 / 3.64) < 1e-12 and pts[-1] == 0.0002623)

# Live DexScreener values replace the post's snapshot when reachable.
live_row = {'priceUsd': '0.0003', 'priceChange': {'m5': 1, 'h1': 2, 'h6': 3, 'h24': 300},
            'volume': {'h24': 900000}, 'liquidity': {'usd': 60000}, 'marketCap': 200000, 'fdv': 210000,
            'txns': {'h24': {'buys': 6000, 'sells': 4000}}, 'info': {}, 'baseToken': {'name': 'Attention Inu'},
            'dexId': 'pumpswap', 'pairAddress': CHART['pairAddress'], 'chainId': 'solana'}
class R:
    status_code = 200
    def json(self): return {'pairs': [live_row]}
orig = d._dex_get
d._dex_get = lambda *a, **k: R()
live = st.card_data(d, CHART, live=True)
d._dex_get = orig
check('live pair data refreshes the numbers', live['price'] == 0.0003 and live['chg24h'] == 300 and live['buys'] == 6000)

# ── the route X fetches ──
client = app.test_client()
r = client.get(f'/api/trade-card/{chart_id}.png', base_url='https://orcagent.fun')
check('the token post has a preview image', r.status_code == 200 and r.headers['Content-Type'] == 'image/png')
im = Image.open(io.BytesIO(r.data))
check("...in X's large-card size (1200x630)", im.size == (1200, 630))
check('...well under X\'s 5MB limit', len(r.data) < 5 * 1024 * 1024)
check('...remote images go through the SSRF check first',
      'https://cdn.example/banner.png' in fetched and 'https://cdn.example/logo.png' in fetched)
# It is the token card, not the old simple picture: its gold "View Token"
# button sits bottom-right and the green 24h chip sits above it.
px = im.convert('RGB')
def near(c, target, tol=40): return all(abs(a - b) <= tol for a, b in zip(c, target))
check('...with the card\'s gold View Token button (bottom right)',
      near(px.getpixel((1149, 558)), (226, 171, 80), 50) and near(px.getpixel((1140, 575)), (40, 33, 21), 12))
check('...and the buy/sell bar in green and red', near(px.getpixel((900, 426)), (54, 215, 160)) and near(px.getpixel((1120, 426)), (255, 113, 106)))

r = client.get(f'/api/trade-card/{text_id}.png', base_url='https://orcagent.fun')
check('a plain text post still has no token-card image', r.status_code == 404)

r = client.get(f'/post/{chart_id}?xv=10', base_url='https://orcagent.fun')
html = r.get_data(as_text=True)
check('the shared post page points X at that image',
      f'<meta name="twitter:image" content="https://orcagent.fun/api/trade-card/{chart_id}.png?v=10">' in html
      and 'summary_large_image' in html)

check('fonts are bundled with their licence',
      all(os.path.exists(os.path.join(st.FONT_DIR, f)) for f in
          ('Geist-ExtraBold.ttf', 'JetBrainsMono-ExtraBold.ttf', 'OFL-Geist.txt', 'OFL-JetBrainsMono.txt')))
raise SystemExit(0 if all(checks) else 1)
