"""Explicit (pornographic) images and videos must never be uploaded.

Real explicit material is not used here. Instead the block threshold is
temporarily forced to 0 (every image counts as explicit) to prove that each
upload path actually enforces the filter, and real safe images are checked
to score far below the production threshold. The model is Yahoo open_nsfw
(BSD-2) via opennsfw-standalone (MIT); see nsfw_filter.py."""
import base64, io, os, sys, time, tempfile, shutil, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('ENCRYPTION_KEY', '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=')

import nsfw_filter as nf
if not nf.available():
    print('SKIP nsfw filter tests: model not installed (deploy/install.sh fetches it)')
    raise SystemExit(0)

from PIL import Image
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

def png(color=(40, 120, 200), size=(320, 240)):
    buf = io.BytesIO(); Image.new('RGB', size, color).save(buf, 'PNG'); return buf.getvalue()

# Safe content scores far below the threshold.
root = os.path.join(os.path.dirname(__file__), '..')
safe = [png(), png((230, 230, 230)), open(os.path.join(root, 'static/icon-512.png'), 'rb').read()]
scores = [nf.score_image_bytes(b) for b in safe]
check('ordinary images score far below the 0.75 block threshold', all(s < 0.2 for s in scores))
check('ordinary images are allowed', all(nf.check_image_bytes(b) is None for b in safe))

import app_entry
d = app_entry._dashboard
app = app_entry.app
WALLET = 'FeLWDoeErzdC26k6HQhXNDdYPpzmAxG1DBP6NoxcLBLD'
d.get_or_create_user(WALLET)
# Start from a clean per-wallet daily video quota (MAX_UPLOADS_PER_DAY) so
# repeated local runs don't trip the limit these tests aren't about.
import sqlite3 as _sq
_c = _sq.connect(d.DB_FILE)
try:
    _c.execute('DELETE FROM video_uploads'); _c.commit()
except _sq.OperationalError:
    pass
_c.close()
d._authenticated_wallet = lambda: WALLET
logged = []
_orig_log = d._log_security_event
d._log_security_event = lambda kind, w, detail='': logged.append((kind, w, detail))

img_uri = 'data:image/png;base64,' + base64.b64encode(png()).decode()
with app.test_client() as c:
    r = c.post('/api/feed/post', json={'content': 'photo', 'image_data': img_uri})
    check('a safe photo post is accepted', r.status_code == 200)
    os.environ['ORCAGENT_NSFW_THRESHOLD'] = '0'
    r = c.post('/api/feed/post', json={'content': 'photo', 'image_data': img_uri})
    body = r.get_json() or {}
    check('an explicit photo post is refused', r.status_code == 400 and 'explicit' in (body.get('msg') or ''))
    check('...and the attempt is logged for moderators', any(k == 'nsfw_blocked' and w == WALLET for k, w, _ in logged))
    r = c.post('/api/avatar', json={'avatar_data': img_uri})
    check('explicit avatars are refused through the same central check', r.status_code == 400)
    del os.environ['ORCAGENT_NSFW_THRESHOLD']

# Videos: sampled frames are checked before the file is ever made public.
ff = shutil.which('ffmpeg')
if not ff:
    try:
        import imageio_ffmpeg; ff = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ff = None
if ff:
    os.environ['ORCAGENT_FFMPEG'] = ff
    media = tempfile.mkdtemp(); os.environ['ORCAGENT_MEDIA_DIR'] = media
    clip = os.path.join(media, 'clip.mp4')
    subprocess.run([ff, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=size=320x240:rate=25',
                    '-t', '5', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', clip], check=True)
    data = open(clip, 'rb').read()
    def upload():
        with app.test_client() as c:
            j = c.post('/api/feed/video/start', json={'size': len(data), 'mime': 'video/mp4'}).get_json()
            if not j.get('ok'):
                return j, None
            vid = j['id']
            c.post(f'/api/feed/video/{vid}/chunk?offset=0', data=data, content_type='application/octet-stream')
            j = c.post(f'/api/feed/video/{vid}/finish').get_json()
            end = time.time() + 90
            while j.get('status') == 'processing' and time.time() < end:
                time.sleep(0.4); j = c.get(f'/api/feed/video/{vid}').get_json()
            return j, vid
    j, vid = upload()
    check('a safe video is processed normally', j.get('status') == 'ready')
    os.environ['ORCAGENT_NSFW_THRESHOLD'] = '0'
    logged.clear()
    j, vid = upload()
    check('an explicit video is refused', j.get('status') == 'failed' and 'explicit' in (j.get('msg') or ''))
    check('...and nothing is left in the public media dir',
          not any(n.startswith(vid) for n in os.listdir(os.path.join(media, 'videos'))))
    check('...and the attempt is logged for moderators', any(k == 'nsfw_blocked' for k, _, _ in logged))
    del os.environ['ORCAGENT_NSFW_THRESHOLD']
    shutil.rmtree(media, ignore_errors=True)
else:
    print('SKIP video part: no ffmpeg')

# Fail-closed on the live server: no model -> no unchecked uploads.
saved = dict(nf._state)
nf._state.update({'session': None, 'tried': True})
os.environ['ORCAGENT_NSFW_REQUIRED'] = '1'
check('when the model is missing in production, image uploads are refused',
      nf.check_image_bytes(png()) == nf.UNAVAILABLE_MSG)
with app.test_client() as c:
    r = c.post('/api/feed/video/start', json={'size': 1000, 'mime': 'video/mp4'})
    check('...and video uploads are refused up front', r.status_code == 503)
os.environ['ORCAGENT_NSFW_REQUIRED'] = '0'
check('outside production a missing model does not block development', nf.check_image_bytes(png()) is None)
nf._state.update(saved)
del os.environ['ORCAGENT_NSFW_REQUIRED']
d._log_security_event = _orig_log

raise SystemExit(0 if all(checks) else 1)
