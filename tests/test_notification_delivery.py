"""DMs and other notifications reach the user: badge, bell and phone.

What was broken:
- the message badge in the navigation counted the legacy wallet `messages`
  table only; every DM the Messages page sends lives in direct_messages, so
  a new DM never showed a badge;
- a phone was only re-registered for push when it had NO subscription. A
  device the server had lost (deleted after a failed push, a restore, a
  wallet switch on the same phone) kept its subscription and was never sent
  to the server again -- DMs and alerts silently stopped. The main app did
  not even run that check;
- opening a conversation left its "X: message" bell entries unread;
- a DM to a user id that does not exist still created a notification row,
  and the push was sent before the message was committed.
"""
import os, sqlite3, sys, tempfile
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

CSRF, BASE = 'tok' * 10, 'https://orcagent.fun'
H = {'X-CSRF-Token': CSRF}
pushed = []
d._send_push_notification = lambda uid, title, body, url='/', icon='', tag='': pushed.append(
    dict(uid=uid, title=title, body=body, url=url, tag=tag))

def member(name):
    w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
    c = sqlite3.connect(d.DB_FILE); c.execute('UPDATE users SET username=? WHERE id=?', (name, uid)); c.commit(); c.close()
    return w, uid

def client(w, uid):
    c = app.test_client()
    with c.session_transaction(base_url=BASE) as s:
        s['wallet'] = w; s['user_id'] = uid; s['csrf_token'] = CSRF
    return c

aw, au = member('alice'); bw, bu = member('bob')
alice, bob = client(aw, au), client(bw, bu)

before = bob.get('/api/messages/unread_count', base_url=BASE).get_json()['count']
r = alice.post(f'/api/messages/{bu}', json={'message': 'hey bob'}, headers=H, base_url=BASE)
check('a DM is sent', r.status_code == 200 and r.get_json().get('ok'))
after = bob.get('/api/messages/unread_count', base_url=BASE).get_json()['count']
check('the message badge in the navigation counts the new DM (it never did)', after == before + 1)
p = [x for x in pushed if x['uid'] == bu]
check('the recipient gets a phone push: sender as title, the text, a link to the chat',
      p and p[-1]['title'] == 'alice' and p[-1]['body'] == 'hey bob' and p[-1]['url'] == '/messages/' + aw)
check('one alert per sender on the phone (a burst updates it instead of stacking)', p and p[-1]['tag'] == 'dm-%d' % au)
src = open(os.path.join(ROOT, 'dashboard.py'), encoding='utf-8').read()
send = src[src.index('def send_dm('):src.index('# ── SUPPORT CHAT (user-facing)')]
check('the push goes out only after the message is stored',
      send.index('conn.commit()') < send.index('_send_push_notification(peer_id'))

def bell(uid):
    c = sqlite3.connect(d.DB_FILE)
    n = c.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0 AND type='message'", (uid,)).fetchone()[0]
    c.close(); return n
check('the bell shows the DM', bell(bu) == 1)
bob.get(f'/api/messages/{au}', base_url=BASE)
check('opening the conversation clears its DM from the bell and the badge',
      bell(bu) == 0 and bob.get('/api/messages/unread_count', base_url=BASE).get_json()['count'] == before)

pushed.clear()
r = alice.post('/api/messages/999999', json={'message': 'anyone?'}, headers=H, base_url=BASE)
c = sqlite3.connect(d.DB_FILE)
ghost = c.execute('SELECT COUNT(*) FROM notifications WHERE user_id=999999').fetchone()[0]; c.close()
check('a DM to a user that does not exist is refused, with no notification or push',
      r.status_code == 404 and ghost == 0 and not pushed)

# ── device registration / test push ─────────────────────────────────────────
st = bob.get('/api/push/status', base_url=BASE).get_json()
check('push status reports whether this user has a registered device', st['ok'] and st['devices'] == 0)
r = bob.post('/api/push/test', json={}, headers=H, base_url=BASE)
check('a test push without any registered device explains what to do',
      r.status_code in (409, 503) and r.get_json()['msg'])
bob.post('/api/push/subscribe', json={'endpoint': 'https://push.example/abc',
                                      'keys': {'p256dh': 'x' * 20, 'auth': 'y' * 10}}, headers=H, base_url=BASE)
st = bob.get('/api/push/status?endpoint=https://push.example/abc', base_url=BASE).get_json()
check('...and sees this device once it is registered', st['devices'] == 1 and st['this_device'])
d._PYWEBPUSH_OK, d.VAPID_PRIVATE_KEY, d.VAPID_PUBLIC_KEY = True, 'k', 'p'
pushed.clear()
r = bob.post('/api/push/test', json={}, headers=H, base_url=BASE)
check('the Settings "Send a test" button pushes to the user\'s own devices',
      r.status_code == 200 and pushed and pushed[-1]['uid'] == bu)
check('push status needs a login', app.test_client().get('/api/push/status', base_url=BASE).status_code == 401)

# ── the phone side ──────────────────────────────────────────────────────────
ps = open(os.path.join(ROOT, 'static', 'push-subscribe.js'), encoding='utf-8').read()
np = open(os.path.join(ROOT, 'static', 'notif-poll.js'), encoding='utf-8').read()
dj = open(os.path.join(ROOT, 'static', 'dashboard.js'), encoding='utf-8').read()
check('every app load re-registers an already-subscribed phone with the server (main app)',
      'function _syncPushSubscription()' in ps and "Notification.permission !== 'granted') return;" in ps
      and 'boot() { _syncPushSubscription(); _armPwaDefaultPush(); _mountPushPrompt(); }' in ps)
check('...and on the standalone pages, where it used to stop as soon as the phone had a subscription',
      'if(sub) return;' not in np and "sessionStorage.getItem('oa_push_synced')" in np
      and "body:JSON.stringify(sub.toJSON())" in np)
check('an iPhone in Safari is told to add OrcAgent to the Home Screen (push only works there)',
      "'ios-browser'" in ps and 'Add to Home Screen' in ps)
check('the in-page fallback never buzzes twice on a device that gets real pushes',
      "if(sessionStorage.getItem('oa_push_synced')) return;" in np)
check('the DM badge is not counted twice now that unread_count includes DMs',
      "_dmSetUnreadBadge(r2.count||0);" in dj and "(r1.ok?r1.unread||0:0)+(r2.count||0)" not in dj)
for page in ('messages.html', 'notifications.html'):
    html = open(os.path.join(ROOT, 'templates', page), encoding='utf-8').read()
    check(f'{page} offers to turn notifications on', 'id="oa-push-prompt"' in html and '/static/push-subscribe.js' in html)
dash = open(os.path.join(ROOT, 'dashboard.html'), encoding='utf-8').read()
check('Settings has a "Send a test" notification button', '_sendTestPush()' in dash)
raise SystemExit(0 if all(checks) else 1)
