"""@orcagent's live posts carry token banner pictures, in layouts that alternate.

Only the token itself, never an app screenshot or mockup: every picture is
built on the token's own Live Market banner (or a backdrop in its logo colour
when it has none) with its live numbers -- three layouts for trending tokens,
two for calls. Pictures are small WebP files served at /media/agent/<hash>.webp
with a long cache, never counted against the rate limit, and removed with
the picture reference after 30 days.
"""
import io, os, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_PLATFORM_POSTS': '0'})
from PIL import Image  # noqa: E402
import app_entry  # noqa: E402
import agent_post_images as A  # noqa: E402
d = app_entry._dashboard
app = app_entry.app

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

pts = [1 + 0.01 * i for i in range(30)]
call = {'id': 1, 'mint': 'M' * 44, 'symbol': 'POPCAT', 'token_name': 'Popcat', 'user': 'chartwizard',
        'note': 'Volume picking up, holding support.', 'price_at_call': 0.000141, 'peak_price': 0.000221,
        'last_price': 0.000207, 'mcap_at_call': 141e6, 'timestamp': '2026-10-07 10:00:00', 'event': 'new', 'image_url': ''}
tok = {'mint': 'M' * 44, 'symbol': 'WIF', 'name': 'dogwifhat', 'price_usd': 1.97, 'price_change_24h': 12.5,
       'volume_24h': 2e6, 'liquidity_usd': 4e5, 'market_cap': 1.9e9, 'buys_24h': 600, 'sells_24h': 400,
       'image_url': '', 'banner_url': '', 'pair_address': ''}
view = A._call_view(d, call)
A._token_art = lambda *a, **k: ('', '')   # no DexScreener in tests
banner = Image.new('RGB', (1500, 500), (90, 40, 140))
sizes = {}
for name in A.TRENDING_DESIGNS:
    data = A.RENDER[name](tok, None, banner, pts)
    im = Image.open(io.BytesIO(data)); sizes[name] = (im.format, im.size, len(data))
for name in A.CALL_DESIGNS:
    data = A.RENDER[name](view, None, banner, [])
    im = Image.open(io.BytesIO(data)); sizes[name] = (im.format, im.size, len(data))
check('only token-banner layouts exist: no app screenshots or phone mockups',
      set(A.RENDER) == {'banner', 'banner_square', 'banner_poster', 'call_banner', 'call_banner_square'}
      and not hasattr(A, 'call_phone') and not hasattr(A, 'trend_chart'))
check('every layout draws a WebP, 4:5 or square',
      all(f == 'WEBP' for f, _, _ in sizes.values())
      and {sz for _, sz, _ in sizes.values()} == {(1080, 1350), (1080, 1080)})
top = Image.open(io.BytesIO(A.RENDER['banner_square'](tok, None, banner, pts))).convert('RGB').getpixel((540, 200))
check('the token\'s banner is really in the picture', top[2] > top[1] and top[0] > top[1])
check('a token without a banner still gets its layout (backdrop in its colour)',
      Image.open(io.BytesIO(A.RENDER['banner_poster'](tok, None, None, pts))).size == (1080, 1350))
check('...and stays small for the feed (%s KB at most)' % max(s // 1024 for _, _, s in sizes.values()),
      all(s < 150_000 for _, _, s in sizes.values()))
check('the headline says what kind of call it is',
      A._call_view(d, dict(call, event='milestone', milestone=3))['headline'] == '3X CALL'
      and A._call_view(d, dict(call, event='best'))['headline'] == 'CALL OF THE DAY' and view['headline'] == 'NEW CALL')

urls = [A.make(d, {'kind': 'trending', 'data': tok}, 'trending:%d' % i) for i in range(12)]
urls += [A.make(d, {'kind': 'call', 'data': call}, 'call:%d' % i) for i in range(8)]
check('pictures are drawn and stored for both kinds', all(u and u.startswith('/media/agent/') for u in urls))
designs = [A.make(d, {'kind': 'trending', 'data': dict(tok, banner_url='')}, 'x', v) for v in range(3)]
check('given a turn number, consecutive pictures use different layouts',
      len(set(designs)) == 3)
shapes = {Image.open(os.path.join(A.media_dir(d), u.rsplit('/', 1)[1])).size for u in urls}
check('the designs alternate (both shapes appear)', shapes == {(1080, 1350), (1080, 1080)})

client = app.test_client(); BASE = 'https://orcagent.fun'
r = client.get(urls[0], base_url=BASE)
check('a picture is served as WebP with a year-long immutable cache',
      r.status_code == 200 and r.mimetype == 'image/webp' and 'immutable' in r.headers.get('Cache-Control', ''))
check('anything that is not a stored picture is a 404',
      client.get('/media/agent/../orcagent.db', base_url=BASE).status_code == 404
      and client.get('/media/agent/abc.webp', base_url=BASE).status_code == 404)
check('pictures never count against the rate limit', '/media/agent/' in d._GLOBAL_LIMIT_EXEMPT)

import sqlite3
c = sqlite3.connect(d.DB_FILE)
c.execute("INSERT INTO feed_posts (wallet, content, image_url) VALUES ('w', 'old post', ?)", (urls[0],))
c.commit(); c.close()
old = os.path.join(A.media_dir(d), urls[0].rsplit('/', 1)[1])
os.utime(old, (time.time() - 31 * 86400,) * 2)
removed = A.prune(d)
c = sqlite3.connect(d.DB_FILE)
left = c.execute("SELECT image_url FROM feed_posts WHERE content='old post'").fetchone()[0]
c.close()
check('pictures older than 30 days are removed, and so is the reference from their post',
      removed >= 1 and not os.path.exists(old) and left is None)

print('%d/%d' % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
