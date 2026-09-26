"""Group members hear about activity in their groups.

- a new post in a group notifies every other member in the app (it used to
  notify only @tagged members); the author is never notified, and a tagged
  member gets the 'mention' instead of a second notification;
- members with a phone also get a push, tagged per group so a newer push
  replaces the older one, and at most one per member per group per 10 min;
- a member can switch a group's notifications off (🔔), and members who
  turned notifications off entirely get nothing;
- notifications open the group at that post (/groups/<id>#gpost-<id>),
  including replies to and @tags in replies on group posts, which used to
  open the home feed.
"""
import os, sqlite3, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_TRENDING_ALERTS': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

CSRF, BASE = 'tok' * 10, 'https://orcagent.fun'
H = {'X-CSRF-Token': CSRF}

pushed, bulk = [], []
d._send_push_notification = lambda uid, title, body, url='/', *a, **k: pushed.append((uid, title, body, url))
d._send_push_notifications_bulk = lambda ids, title, body, url='/', icon='', tag='': bulk.append(
    (sorted(ids), title, body, url, tag))

def db():
    return sqlite3.connect(d.DB_FILE)

def member(name):
    w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
    c = db(); c.execute('UPDATE users SET username=? WHERE id=?', (name, uid)); c.commit(); c.close()
    return w, uid

def client(w, uid):
    c = app.test_client()
    with c.session_transaction(base_url=BASE) as s:
        s['wallet'] = w; s['user_id'] = uid; s['csrf_token'] = CSRF
    return c

alice, bob, carol, dave, erin, outsider = (member(n) for n in ('alice', 'bob', 'carol', 'dave', 'erin', 'olly'))
c = db()
gid = c.execute("INSERT INTO groups (token_symbol, name, created_by) VALUES ('ORC','ORCAGENT',?)",
                (alice[1],)).lastrowid
c.execute("INSERT INTO group_members (group_id, user_id, role) VALUES (?,?,'owner')", (gid, alice[1]))
for m in (bob, carol, dave, erin):
    c.execute("INSERT INTO group_members (group_id, user_id) VALUES (?,?)", (gid, m[1]))
# bob, carol and erin have a phone; erin turned notifications off entirely.
for i, m in enumerate((bob, carol, erin)):
    c.execute('INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth) VALUES (?,?,?,?)',
              (m[1], f'https://push.example/{i}', 'k', 'a'))
c.execute('UPDATE users SET pref_notifications=0 WHERE id=?', (erin[1],))
c.commit(); c.close()

A, B, C = client(*alice), client(*bob), client(*carol)

def notes(uid, type_=None):
    c = db()
    q = 'SELECT type, content, link FROM notifications WHERE user_id=?' + (' AND type=?' if type_ else '') + ' ORDER BY id'
    rows = c.execute(q, (uid, type_) if type_ else (uid,)).fetchall()
    c.close(); return rows

def post(cl, content):
    r = cl.post(f'/api/groups/{gid}/posts', json={'content': content}, headers=H, base_url=BASE)
    return r.get_json()['post_id']

# ── a new post notifies the other members ──
p1 = post(A, 'gm team, $ORC is sending 🚀 @dave')
link1 = f'/groups/{gid}#gpost-{p1}'
check('a new post notifies another member in the app',
      notes(bob[1], 'group_post') == [('group_post', f'alice posted in ORCAGENT: gm team, $ORC is sending 🚀 @dave', link1)])
check('...every other member', len(notes(carol[1], 'group_post')) == 1)
check('...but never the author', notes(alice[1]) == [])
check('...a tagged member gets the mention, not a second notification',
      notes(dave[1]) == [('mention', 'alice mentioned you in ORCAGENT', link1)])
check('...members who turned notifications off get nothing', notes(erin[1]) == [])
check('...and non-members get nothing', notes(outsider[1]) == [])
check('members with a phone get one push, tagged for this group',
      bulk == [(sorted([bob[1], carol[1]]), 'ORCAGENT', 'alice: gm team, $ORC is sending 🚀 @dave', link1, f'orc-group-{gid}')])

# ── a busy group does not ring the phone for every message ──
bulk.clear()
p2 = post(A, 'second one')
check('a second post within 10 minutes is in the app...', len(notes(bob[1], 'group_post')) == 2)
check('...but does not push again', bulk == [])
c = db(); c.execute("UPDATE notifications SET created_at=datetime('now','-11 minutes')"); c.commit(); c.close()
post(A, 'third, later')
check('after 10 quiet minutes the next post pushes again', bulk and bulk[0][0] == sorted([bob[1], carol[1]]))

# ── the 🔔 switch ──
g = B.get(f'/api/groups/{gid}', base_url=BASE).get_json()['group']
check('a member sees notifications on by default', g['notify'] is True)
r = B.post(f'/api/groups/{gid}/notifications', json={'on': False}, headers=H, base_url=BASE).get_json()
check('a member can switch this group off', r == {'ok': True, 'notify': False}
      and B.get(f'/api/groups/{gid}', base_url=BASE).get_json()['group']['notify'] is False)
before = len(notes(bob[1], 'group_post'))
bulk.clear()
post(C, 'carol here')
check('...and then hears nothing about new posts', len(notes(bob[1], 'group_post')) == before
      and all(bob[1] not in b[0] for b in bulk))
check('...while the others still do', notes(alice[1], 'group_post')[-1][1] == 'carol posted in ORCAGENT: carol here')
B.post(f'/api/groups/{gid}/notifications', json={'on': True}, headers=H, base_url=BASE)
post(C, 'back on')
check('switching it back on works', len(notes(bob[1], 'group_post')) == before + 1)
out = client(*outsider)
check('a non-member cannot switch notifications',
      out.post(f'/api/groups/{gid}/notifications', json={'on': True}, headers=H, base_url=BASE).status_code == 403)
check('a guest cannot either',
      app.test_client().post(f'/api/groups/{gid}/notifications', json={'on': True}, headers=H,
                             base_url=BASE).status_code in (401, 403))
check('non-members see no switch', out.get(f'/api/groups/{gid}', base_url=BASE).get_json()['group']['notify'] is False)

# ── a photo-only post still reads well ──
img = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
A.post(f'/api/groups/{gid}/posts', json={'content': '', 'image_data': img}, headers=H, base_url=BASE)
check('a photo post says "📷 Photo"', notes(carol[1], 'group_post')[-1][1] == 'alice posted in ORCAGENT: 📷 Photo')

# ── replies on group posts open the group, not the home feed ──
pushed.clear()
r = B.post('/api/feed/reply', json={'post_id': f'g{p2}', 'message': 'lfg @carol'}, headers=H, base_url=BASE)
link2 = f'/groups/{gid}#gpost-{p2}'
check('reply to a group post is accepted', r.get_json().get('ok'))
check("the author's reply notification opens the group post", notes(alice[1], 'reply')[-1][2] == link2)
check('...and so does its push', any(p[0] == alice[1] and p[3] == link2 for p in pushed))
check('an @tag in that reply opens the group post too', notes(carol[1], 'mention')[-1][2] == link2)

# ── the page: bell and jump-to-post ──
html = open(os.path.join(os.path.dirname(__file__), '..', 'templates', 'group_detail.html')).read()
check('the group page has the 🔔 switch', 'id="gd-notify-btn" onclick="_toggleGroupNotify()"' in html
      and "'/api/groups/'+_groupId+'/notifications'" in html)
check('...and scrolls to the post a notification links to', '#gpost-' in html and '_focusLinkedPost();' in html)
raise SystemExit(0 if all(checks) else 1)
