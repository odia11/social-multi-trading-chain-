"""What actually filled the Railway volume, and what stops it filling again.

Every uploaded picture in this app is kept as a base64 data URI in a TEXT
column. A photo does not land on the filesystem -- it lands in orcagent.db,
and base64 adds a third on top of it. A 3 MB phone photo becomes about 4 MB
of database, a few hundred of them are gigabytes, and that database is what
the volume holds and what every backup copies.

The size limits that existed only capped how big a single upload could be.
They did nothing about the fact that a full-width feed photo does not need
3 MB to be displayed at 1000 pixels wide.

So: re-encode once, on the way in. The rules that matter are that it always
makes things smaller, that it never loses something the user would notice
(transparency, a GIF's animation), and above all that it can NEVER be the
reason a post fails -- it runs on the upload path of every picture in the app.
"""
import base64
import io
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, '/home/user/Orc-agent-Solana-chain-')
from PIL import Image                                             # noqa: E402

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def uri(img, fmt='JPEG', **kw):
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kw)
    mime = {'JPEG': 'jpeg', 'PNG': 'png', 'GIF': 'gif', 'WEBP': 'webp'}[fmt]
    return 'data:image/' + mime + ';base64,' + base64.b64encode(buf.getvalue()).decode()


def raw_bytes(u):
    return len(base64.b64decode(u.partition(',')[2]))


def photo(w, h, seed=7):
    """Noise, not flat colour: a flat image compresses to nothing and would
    make every saving here look spectacular and mean nothing."""
    import random
    random.seed(seed)
    im = Image.new('RGB', (w, h))
    im.putdata([(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                for _ in range(w * h)])
    return im


# The module runs its own startup in a subprocess elsewhere; here only the two
# functions are needed, so they are pulled out of the source without importing
# the app.
import ast, types                                                 # noqa: E402
SRC = open('/home/user/Orc-agent-Solana-chain-/dashboard.py').read()
tree = ast.parse(SRC)
wanted = {'_shrink_image_data_uri', '_shrink_image_bytes'}
mod = types.ModuleType('shrinker')
mod.__dict__.update({'base64': base64, 'io': io, 'Image': Image, 'print': print,
                     'IMAGE_MAX_EDGE': 1600, 'IMAGE_TARGET_KB': 400,
                     'IMAGE_AVATAR_EDGE': 512})
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in wanted:
        exec(compile(ast.Module([node], []), '<shrinker>', 'exec'), mod.__dict__)
shrink = mod._shrink_image_data_uri
shrink_bytes = mod._shrink_image_bytes
check('both helpers were found in dashboard.py',
      callable(shrink) and callable(shrink_bytes))


# ── the case that filled the volume ──
big = uri(photo(4000, 3000), 'JPEG', quality=95)
before = raw_bytes(big)
out = shrink(big)
after = raw_bytes(out)
check(f'a 4000x3000 phone photo ({before//1024} KB) is re-encoded down to '
      f'{after//1024} KB — the size limits only capped a single upload, they '
      f'did nothing about storing far more resolution than any screen shows',
      after < before)
check('...to under the 400 KB target', after <= 400 * 1024)
check('...at least 5x smaller, which is the difference between a volume that '
      'fills in weeks and one that does not', after * 5 < before)
w, h = Image.open(io.BytesIO(base64.b64decode(out.partition(',')[2]))).size
check(f'...and no longer than 1600px on the long side (now {w}x{h})',
      max(w, h) <= 1600)
check('...keeping its aspect ratio', abs((w / h) - (4000 / 3000)) < 0.02)
check('the result is still a valid data URI the app can store as-is',
      out.startswith('data:image/') and ';base64,' in out)


# ── it must never make anything bigger ──
tiny = uri(photo(40, 30), 'JPEG', quality=60)
check('an image already smaller than anything this would produce is returned '
      'UNCHANGED — re-encoding it would only lose quality for nothing',
      shrink(tiny) == tiny)

for n, im in (('a 200x200 avatar', photo(200, 200)),
              ('a 1600x900 screenshot', photo(1600, 900))):
    o = shrink(uri(im))
    check(f'{n} never comes back larger than it went in',
          raw_bytes(o) <= raw_bytes(uri(im)))


# ── things a user would notice ──
alpha = Image.new('RGBA', (2000, 2000), (255, 0, 0, 128))
out_a = shrink(uri(alpha, 'PNG'))
im_a = Image.open(io.BytesIO(base64.b64decode(out_a.partition(',')[2])))
check('an image with transparency stays PNG and keeps its alpha channel — '
      'flattening a logo onto black is exactly the kind of silent damage this '
      'must not do', out_a.startswith('data:image/png') and im_a.mode == 'RGBA')
check('...and is still shrunk', max(im_a.size) <= 1600)

frames = [Image.new('P', (600, 600), i) for i in (1, 2, 3)]
gbuf = io.BytesIO()
frames[0].save(gbuf, format='GIF', save_all=True, append_images=frames[1:], duration=100)
gif = 'data:image/gif;base64,' + base64.b64encode(gbuf.getvalue()).decode()
check('an ANIMATED GIF is returned untouched. Re-encoding one through a single '
      'frame would quietly turn a user\'s animation into a still, which is worse '
      'than storing it whole', shrink(gif) == gif)

still_gif = uri(photo(2000, 2000).convert('P'), 'GIF')
check('...while a still GIF is fair game', raw_bytes(shrink(still_gif)) < raw_bytes(still_gif))


# ── it can never break an upload ──
for bad, why in (('', 'an empty string'),
                 ('not a data uri at all', 'plain text'),
                 ('data:image/png;base64,', 'a header with no payload'),
                 ('data:image/png;base64,!!!!not-base64!!!!', 'invalid base64'),
                 ('data:image/png;base64,' + base64.b64encode(b'nonsense').decode(),
                  'bytes that are not an image'),
                 ('data:text/plain;base64,aGk=', 'a non-image data URI')):
    check(f'{why} comes straight back rather than raising — this runs on the '
          f'upload path of every picture in the app and must never be the '
          f'reason a post fails', shrink(bad) == bad)
check('None does not raise either', shrink(None) is None)


# ── the file-upload path ──
data = base64.b64decode(uri(photo(3000, 2000)).partition(',')[2])
out_b, ext_b = shrink_bytes(data, 'jpg')
check(f'a real uploaded FILE is shrunk too ({len(data)//1024} KB -> '
      f'{len(out_b)//1024} KB)', len(out_b) < len(data))
check('...and keeps a sensible extension', ext_b in ('jpg', 'jpeg'))
check('a file it cannot read is returned untouched with its extension',
      shrink_bytes(b'not an image', 'png') == (b'not an image', 'png'))
png_alpha = io.BytesIO()
Image.new('RGBA', (2000, 2000), (0, 255, 0, 100)).save(png_alpha, format='PNG')
o2, e2 = shrink_bytes(png_alpha.getvalue(), 'png')
check('...and a transparent PNG file stays a png', e2 == 'png')


# ── it is actually wired in ──
fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
wired = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
         and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                 and c.func.id in ('_shrink_image_data_uri', '_shrink_image_bytes')
                 for c in ast.walk(n))]
check(f'every upload path shrinks before storing — {len(wired)} of them: '
      + ', '.join(sorted(set(wired))), len(set(wired)) >= 6)

# Shrinking has to happen BEFORE the size check, or a photo is rejected for
# being too large when the stored copy would have been well under the limit.
for name in set(wired):
    src = ast.get_source_segment(SRC, fns[name]) or ''
    if '_shrink_image_data_uri' not in src or 'Image too large' not in src:
        continue
    check(f'{name} shrinks BEFORE it measures, so a photo is not rejected at a '
          f'size the stored copy would never have had',
          src.index('_shrink_image_data_uri') < src.index('Image too large'))

check('the storage line reports how much of the database is pictures, since '
      'that is the largest thing in it and nobody could see it before',
      'of which images' in SRC and '_stored_image_bytes' in SRC)


# ── reclaiming what is already stored ──────────────────────────────────────
# Shrink-on-upload stops the volume growing. It frees nothing already on it,
# and the volume is already full -- so there has to be a way to compact what
# is there. It is an owner action rather than a maintenance job, because it
# rewrites photos people have already published.
compact = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                and n.name == 'admin_compact_images'), None)
check('there is a way to compact images already stored', compact is not None)
csrc = ast.get_source_segment(SRC, compact) or ''
check('it is owner-only', '_is_owner(wallet)' in csrc and '_owner_denied' in csrc)
check('it REPORTS by default and only rewrites when explicitly asked to — this '
      'changes content people have already published, so it is not something a '
      'background job should decide',
      "get('apply')" in csrc and "request.method == 'POST'" in csrc)
check('...and says plainly that the originals are not kept',
      'does not keep the originals' in csrc)
check('it VACUUMs after rewriting. Without that, SQLite keeps the freed pages '
      'for itself and the volume looks exactly as full as before',
      "'VACUUM'" in csrc and 'wal_checkpoint' in csrc)
check('...and says so when the rewrite worked but the VACUUM did not, rather '
      'than reporting space that was not actually returned',
      'not yet on the volume' in csrc)
check('a failure rolls back rather than leaving half the images rewritten',
      'conn.rollback()' in csrc)
check('it reuses the same shrinker as the upload path, so an old image ends up '
      'the size a new one would', '_shrink_image_data_uri' in csrc)
check('a table or column that does not exist is skipped, not fatal',
      'except sqlite3.Error' in csrc)
check('it reports the storage picture alongside, so the effect is visible',
      '_storage_breakdown()' in csrc)


# ── end to end, on a real database ──
import sqlite3                                                    # noqa: E402
db = tempfile.mktemp(suffix='.db')
conn = sqlite3.connect(db)
conn.execute('CREATE TABLE feed_posts (id INTEGER PRIMARY KEY, image_url TEXT)')
fat = uri(photo(3000, 2000))
conn.execute('INSERT INTO feed_posts (image_url) VALUES (?)', (fat,))
conn.execute('INSERT INTO feed_posts (image_url) VALUES (?)', ('just text',))
conn.commit()

rows = conn.execute("SELECT id, image_url FROM feed_posts WHERE image_url LIKE 'data:image/%'").fetchall()
check('the query the endpoint uses finds only the images, not the text posts',
      len(rows) == 1)
b, a = len(rows[0][1]), len(shrink(rows[0][1]))
check(f'compacting one stored 3000x2000 photo takes it from {b//1024} KB to '
      f'{a//1024} KB of database', a * 4 < b)
conn.close()
os.unlink(db)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
