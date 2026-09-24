"""Video posts (max 30 s), end to end through the real Flask app and a real
ffmpeg: chunked upload -> server-side re-encode -> post -> feed -> playback.

Checks the rules that matter: the 30-second limit is enforced on the file
itself, non-videos are refused, location metadata never reaches the public
file, only the uploader can post their video (once), chunks resume on the
server's offset, and playback supports range requests."""
import os, sys, time, tempfile, subprocess, shutil, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('ENCRYPTION_KEY', '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=')

ff = shutil.which('ffmpeg')
if not ff:
    try:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ff = None
if not ff:
    print('SKIP video upload tests: no ffmpeg available')
    raise SystemExit(0)
os.environ['ORCAGENT_FFMPEG'] = ff
media = tempfile.mkdtemp()
os.environ['ORCAGENT_MEDIA_DIR'] = media

import app_entry
import video_uploads as vu
d = app_entry._dashboard
app = app_entry.app
vu.CHUNK_BYTES = 40_000        # force several chunks with small test clips

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

tmp = tempfile.mkdtemp()
def make(name, seconds, size='720x1280', meta=True):
    out = os.path.join(tmp, name)
    cmd = [ff, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', f'testsrc=size={size}:rate=30',
           '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', str(seconds), '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
           '-c:a', 'aac', '-movflags', 'use_metadata_tags']
    if meta:
        cmd += ['-metadata', 'location=+52.3676+004.9041/', '-metadata', 'comment=SECRET-GPS']
    subprocess.run(cmd + [out], check=True)
    return out

ALICE = 'FeLWDoeErzdC26k6HQhXNDdYPpzmAxG1DBP6NoxcLBLD'
BOB = 'Cdn8WftaYycdudV9yeeQPY1A1Tgo1bMa9eV4Tv9SeAM9'
for w in (ALICE, BOB):
    d.get_or_create_user(w)
who = {'w': ALICE}
# Start from a clean per-wallet daily video quota (MAX_UPLOADS_PER_DAY) so
# repeated local runs don't trip the limit these tests aren't about.
import sqlite3 as _sq
_c = _sq.connect(d.DB_FILE)
try:
    _c.execute('DELETE FROM video_uploads'); _c.commit()
except _sq.OperationalError:
    pass
_c.close()
d._authenticated_wallet = lambda: who['w']

def upload(path, mime='video/mp4'):
    data = open(path, 'rb').read()
    with app.test_client() as c:
        r = c.post('/api/feed/video/start', json={'size': len(data), 'mime': mime})
        j = r.get_json()
        if not j.get('ok'):
            return j, None
        vid, off = j['id'], 0
        while off < len(data):
            piece = data[off:off + vu.CHUNK_BYTES]
            r = c.post(f'/api/feed/video/{vid}/chunk?offset={off}', data=piece,
                       content_type='application/octet-stream')
            cj = r.get_json()
            if r.status_code == 409 and 'received' in cj:
                off = cj['received']; continue
            if not cj.get('ok'):
                return cj, vid
            off = cj['received']
        j = c.post(f'/api/feed/video/{vid}/finish').get_json()
        end = time.time() + 120
        while j.get('status') == 'processing' and time.time() < end:
            time.sleep(0.5)
            j = c.get(f'/api/feed/video/{vid}').get_json()
        return j, vid

# 1. A 6s portrait phone-style clip with GPS metadata.
j, vid = upload(make('ok.mp4', 6, meta=True))
check('a 6-second video uploads in chunks and is processed', j.get('status') == 'ready' and j.get('url', '').endswith('.mp4'))
out = os.path.join(media, 'videos', vid + '.mp4')
check('the published file exists and is world-readable for nginx', os.path.exists(out) and oct(os.stat(out).st_mode)[-3:] == '644')
blob = open(out, 'rb').read()
check('location / comment metadata is stripped from the published file', b'SECRET-GPS' not in blob and b'52.3676' not in blob)
probe = subprocess.run([ff, '-hide_banner', '-i', out], capture_output=True, text=True).stderr
check('re-encoded to H.264 with the short side capped at 720px', 'h264' in probe and ('720x1280' in probe))
check('a poster frame is generated', os.path.exists(os.path.join(media, 'videos', vid + '.jpg')) and j.get('poster', '').endswith('.jpg'))
check('moov atom first (+faststart) so playback starts immediately', blob.find(b'moov') < blob.find(b'mdat'))

# 2. Posting it: only by the uploader, only once.
with app.test_client() as c:
    who['w'] = BOB
    r = c.post('/api/feed/post', json={'content': '', 'video_id': vid})
    check("someone else can't post your uploaded video", r.status_code == 400)
    who['w'] = ALICE
    r = c.post('/api/feed/post', json={'content': 'my first clip', 'video_id': vid})
    pid = (r.get_json() or {}).get('id')
    check('the uploader can post it', r.status_code == 200 and pid)
    r = c.post('/api/feed/post', json={'content': 'again', 'video_id': vid})
    check('the same video cannot be posted twice', r.status_code == 400)
    r = c.post('/api/feed/post', json={'content': '', 'video_id': vid, 'image_data': 'data:image/png;base64,AAAA'})
    check('a post cannot carry both an image and a video', r.status_code == 400)
    feed = c.get('/api/social/feed?filter=all').get_json()
    item = next((i for i in feed.get('items', []) if i.get('id') == pid), None)
    check('the feed item carries video_url + poster', item and item.get('video_url') == j['url'] and item.get('video_poster') == j['poster'])
    single = c.get(f'/api/feed/post/p{pid}').get_json() if hasattr(app, 'url_map') else {}
    r = c.get(j['url'], headers={'Range': 'bytes=0-99'})
    check('playback supports range requests (206) with the right type', r.status_code == 206 and r.mimetype == 'video/mp4' and len(r.data) == 100)
    check('media is served nosniff + immutable', r.headers.get('X-Content-Type-Options') == 'nosniff' and 'immutable' in r.headers.get('Cache-Control', ''))
    check('only processed file names are served', c.get('/media/videos/..%2Forcagent.db').status_code == 404)

# 3. Longer than 30 seconds: refused from the file itself.
j, vid35 = upload(make('long.mp4', 35, size='320x240', meta=False))
check('a 35-second video is refused server-side', j.get('status') == 'failed' and '30 seconds' in (j.get('msg') or ''))
check('...and nothing is published for it', not os.path.exists(os.path.join(media, 'videos', vid35 + '.mp4')))

# 4. Not a video.
bad = os.path.join(tmp, 'fake.mp4'); open(bad, 'wb').write(b'<html><script>alert(1)</script>' * 50)
j, _ = upload(bad)
check('a non-video file is refused at the first chunk', j.get('ok') is False and 'not a video' in (j.get('msg') or ''))

# 5. Limits.
with app.test_client() as c:
    r = c.post('/api/feed/video/start', json={'size': 200 * 1024 * 1024, 'mime': 'video/mp4'})
    check('files above the size cap are refused before uploading', r.status_code == 400)
    r = c.post('/api/feed/video/start', json={'size': 1000, 'mime': 'image/png'})
    check('non-video MIME types are refused', r.status_code == 400)

# 6. Deleting the post removes the published files (via cleanup).
with app.test_client() as c:
    c.delete(f'/api/feed/post/{pid}')
d._video_cleanup(force=True)
check('deleting the post removes its video and poster', not os.path.exists(out) and not os.path.exists(os.path.join(media, 'videos', vid + '.jpg')))

shutil.rmtree(tmp, ignore_errors=True); shutil.rmtree(media, ignore_errors=True)
raise SystemExit(0 if all(checks) else 1)
