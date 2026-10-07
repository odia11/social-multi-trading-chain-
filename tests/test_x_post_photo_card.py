"""A post shared to X shows its photo.

The share link /post/<id> told X the picture was 1200x630 while posts carry
square or portrait photos, so X cropped them or showed no picture; pictures
@orcagent drew (/media/agent/...) got no X picture at all; and every share
used the same ?xv=9, so a link X had read before kept its old, picture-less
card. Now:

- the X picture is a 1200x630 JPEG with the whole photo fitted on a blurred
  copy of itself, for uploaded photos and for @orcagent's pictures alike;
- the tags say exactly that (image/jpeg, 1200x630, a .jpg URL);
- the share version moved to ?xv=10, so X fetches every post again.
"""
import base64, io, os, re, sqlite3, sys, tempfile
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_PLATFORM_POSTS': '0'})
from PIL import Image  # noqa: E402
import app_entry  # noqa: E402
import agent_post_images  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
d = app_entry._dashboard
app = app_entry.app

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

w = str(Keypair().pubkey()); d.get_or_create_user(w)
buf = io.BytesIO()
photo = Image.new('RGB', (600, 900), (220, 40, 40))       # a portrait photo, red
photo.save(buf, 'JPEG', quality=95)
uri = 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()
agent_url = agent_post_images.save(d, (lambda b: (Image.new('RGB', (1080, 1080), (40, 40, 220)).save(b, 'WEBP'), b.getvalue())[1])(io.BytesIO()))
c = sqlite3.connect(d.DB_FILE)
user_post = c.execute("INSERT INTO feed_posts (wallet, content, image_url) VALUES (?,?,?)", (w, '$swordcat', uri)).lastrowid
agent_post = c.execute("INSERT INTO feed_posts (wallet, content, image_url) VALUES (?,?,?)", (w, '$WIF is trending', agent_url)).lastrowid
text_post = c.execute("INSERT INTO feed_posts (wallet, content) VALUES (?,?)", (w, 'just words')).lastrowid
c.commit(); c.close()

client = app.test_client(); BASE = 'https://orcagent.fun'
BOT = {'User-Agent': 'Twitterbot/1.0'}

def card(post_id):
    body = client.get('/post/p%d?xv=10' % post_id, base_url=BASE, headers=BOT).get_data(as_text=True)
    m = re.search(r'name="twitter:image" content="([^"]+)"', body)
    return body, (m.group(1) if m else '')

body, url = card(user_post)
check('X is told a large-image card with a .jpg picture for a photo post',
      'summary_large_image' in body and url.endswith('.jpg?v=10') and '/api/post-og-image/p%d.jpg' % user_post in url)
check('...declared exactly as served: image/jpeg, 1200x630',
      'og:image:type" content="image/jpeg"' in body and 'og:image:width" content="1200"' in body
      and 'og:image:height" content="630"' in body)
r = client.get(url.replace(BASE, ''), base_url=BASE, headers=BOT)
img = Image.open(io.BytesIO(r.data)).convert('RGB')
check('the picture X fetches is a 1200x630 JPEG with a long cache',
      r.status_code == 200 and r.mimetype == 'image/jpeg' and img.size == (1200, 630)
      and 'max-age=31536000' in r.headers.get('Cache-Control', ''))
top, middle, bottom = img.getpixel((600, 3)), img.getpixel((600, 315)), img.getpixel((600, 626))
check('the whole portrait photo is in it, top to bottom (not cropped)',
      all(p[0] > 180 and p[1] < 90 for p in (top, middle, bottom)))
side = img.getpixel((40, 315))
check('...on a darker blurred copy of itself beside it', side[0] < middle[0] - 60)

body, url = card(agent_post)
r = client.get(url.replace(BASE, ''), base_url=BASE, headers=BOT)
check('a picture @orcagent drew also becomes the X picture',
      url and r.status_code == 200 and Image.open(io.BytesIO(r.data)).size == (1200, 630))
check('a post without a picture keeps the normal site card', not card(text_post)[1].endswith('.jpg?v=10'))
JS = open(os.path.join(ROOT, 'static', 'dashboard.js'), encoding='utf-8').read()
import x_share_cache_bust
check('shares use ?xv=10, so X reads every post again',
      "'?xv=10'" in JS and "'?xv=9'" not in JS and x_share_cache_bust._PREVIEW_VERSION == '10')

print('%d/%d' % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
