"""Feed posts have no separate emoji-reaction button.

Each post's action row showed a smiley with a count next to the like
button. It is not needed next to the like, and every open feed asked the server for
those counts every 12 seconds. The button, its palette and that poll are gone;
reply, repost, like, share and views stay.
"""
import os
ROOT = os.path.join(os.path.dirname(__file__), '..')
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

js = read('static', 'dashboard.js'); html = read('dashboard.html')
check('a feed card renders no emoji-reaction button or palette',
      'fc-emoji-react-btn' not in js and 'fc-react-palette' not in js and "'rbtn-'" not in js)
check('the feed no longer polls reaction counts every 12 s',
      '_refreshVisibleReactions' not in js and '/api/feed/reactions/batch' not in js)
check('its leftover styles are gone',
      'fc-emoji-react-btn' not in html and 'fc-react-' not in html and 'fc-reaction-pill' not in html)
check('reply, repost, like, share and the view count are still on every card',
      all(k in js for k in ("fc-reply-btn", "fc-repost-btn", "fc-like-btn", "fc-share-btn", "fc-view-count")))
print('%d/%d' % (sum(checks), len(checks)))
raise SystemExit(0 if all(checks) else 1)
