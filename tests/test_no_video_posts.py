"""Users may not post videos.

- The Home composer has no Video button, no video file picker and no video
  preview; the page script no longer uploads videos.
- The server refuses too, so a direct API call cannot get around it:
  starting a video upload and posting with a video_id both answer 403, and
  nothing is stored.
- Videos posted before this change still play in the feed.
- The Call button has its own crosshair icon, not the old speaker.
"""
import os, re, sqlite3, sys, tempfile
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck='})
os.environ.pop('ORCAGENT_FEED_VIDEO_POSTS', None)
import app_entry  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

html = open(os.path.join(ROOT, 'dashboard.html')).read()
js = open(os.path.join(ROOT, 'static', 'dashboard.js')).read()
check('the composer has no Video button', 'video-pill-btn' not in html and '>Video<' not in html)
check('...no video file picker or video preview', 'composer-video' not in html and 'accept="video' not in html)
check('...and the page script no longer uploads videos',
      '/api/feed/video/start' not in js and 'video_id' not in js and '_composerVideo' not in js)
check('videos posted before this change still play in the feed', 'class="fc-post-video"' in js)

call = re.search(r'id="call-pill-btn".*?</svg>', html, re.S).group(0)
check('the Call button has a crosshair icon, not the old speaker',
      '<circle cx="12" cy="12" r="8"/>' in call and 'M15 9a4 4 0 0 1 0 6' not in call)

w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
client = app.test_client()
BASE = 'https://orcagent.fun'
with client.session_transaction(base_url=BASE) as s:
    s['wallet'] = w; s['user_id'] = uid; s['csrf_token'] = 'x' * 40
H = {'X-CSRF-Token': 'x' * 40}
r = client.post('/api/feed/video/start', json={'size': 1000, 'mime': 'video/mp4'}, headers=H, base_url=BASE)
check('the server refuses to start a video upload',
      r.status_code == 403 and r.get_json()['msg'] == 'Video posts are not allowed on OrcAgent')
c = sqlite3.connect(d.DB_FILE)
before = c.execute('SELECT COUNT(*) FROM feed_posts').fetchone()[0]
r = client.post('/api/feed/post', json={'content': 'look', 'video_id': 'a' * 32}, headers=H, base_url=BASE)
after = c.execute('SELECT COUNT(*) FROM feed_posts').fetchone()[0]
check('...and refuses a post with a video, storing nothing',
      r.status_code == 403 and 'not allowed' in r.get_json()['msg'] and after == before)
r = client.post('/api/feed/post', json={'content': 'text posts still work'}, headers=H, base_url=BASE)
check('text posts still work', r.status_code == 200 and r.get_json().get('ok'))
c.close()
raise SystemExit(0 if all(checks) else 1)
