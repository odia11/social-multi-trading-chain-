"""Sharing https://orcagent.fun on X shows a real preview image.

X showed a grey placeholder: the home page's only image was the square
512x512 app icon (X wants a wide 1200x630 image for a large card), there was
no twitter:image, and every preview tag sat ~250KB deep in the page, behind
inline styles and scripts, where link-preview crawlers may stop reading.
Now the page carries a 1200x630 preview image with full og:/twitter: tags at
the top of <head>.
"""
import os, re, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_TRENDING_ALERTS': '0'})
import app_entry  # noqa: E402
from PIL import Image  # noqa: E402
app = app_entry.app

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

IMG = 'https://orcagent.fun/static/og-orcagent.png'
c = app.test_client()
H = {'User-Agent': 'Twitterbot/1.0'}
html = c.get('/', base_url='https://orcagent.fun', headers=H).get_data(as_text=True)
def meta(attr, name):
    m = re.search(r'<meta %s="%s" content="([^"]*)">' % (attr, re.escape(name)), html)
    return m.group(1) if m else None

check('home has a large-image X card', meta('name', 'twitter:card') == 'summary_large_image')
check('...with twitter:image set to the 1200x630 preview', meta('name', 'twitter:image') == IMG)
check('...and og:image the same, with its size and type',
      meta('property', 'og:image') == IMG and meta('property', 'og:image:width') == '1200'
      and meta('property', 'og:image:height') == '630' and meta('property', 'og:image:type') == 'image/png')
check('...plus title, description, alt text and the @Orcagent handle',
      meta('name', 'twitter:title') and meta('name', 'twitter:description')
      and meta('name', 'twitter:image:alt') and meta('name', 'twitter:site') == '@Orcagent')
check('no longer the square app icon', 'icon-512.png' not in (meta('property', 'og:image') or ''))
check('the tags are at the top of the page (crawlers read only the start)',
      0 < html.find('twitter:image') < 8000 and html.find('og:image') < 8000)
check('...after the charset declaration, which must stay first',
      html.lower().find('<meta charset') < html.find('og:type'))
check('each tag appears once', html.count('property="og:image"') == 1 and html.count('name="twitter:card"') == 1)

path = os.path.join(os.path.dirname(__file__), '..', 'static', 'og-orcagent.png')
im = Image.open(path)
check('the preview image is 1200x630 and well under 5MB', im.size == (1200, 630) and os.path.getsize(path) < 1_000_000)
r = c.get('/static/og-orcagent.png', base_url='https://orcagent.fun', headers=H)
check('...served as a crawlable PNG', r.status_code == 200 and r.mimetype == 'image/png'
      and 'noindex' not in (r.headers.get('X-Robots-Tag') or ''))

lm = c.get('/live-market', base_url='https://orcagent.fun', headers=H).get_data(as_text=True)
check('other public pages get the same preview', 'name="twitter:image" content="' + IMG + '"' in lm)
raise SystemExit(0 if all(checks) else 1)
