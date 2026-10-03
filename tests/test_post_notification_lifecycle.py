"""Post notifications follow the post lifecycle instead of becoming ghost alerts."""
import os, sqlite3, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update({
    'DATA_DIR': tempfile.mkdtemp(),
    'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
    'ORCAGENT_FRONTS_GAS': '0',
})
import app_entry  # noqa: E402
from solders.keypair import Keypair  # noqa: E402

d = app_entry._dashboard
app = app_entry.app
BASE = 'https://orcagent.fun'
CSRF = 'post-life-token'
HEADERS = {'X-CSRF-Token': CSRF}
d._send_push_notifications_bulk = lambda *a, **k: None
d._send_push_notification = lambda *a, **k: None

def member(name):
    wallet = str(Keypair().pubkey())
    uid = d.get_or_create_user(wallet)
    with sqlite3.connect(d.DB_FILE) as conn:
        conn.execute('UPDATE users SET username=? WHERE id=?', (name, uid))
    return wallet, uid

def client(wallet, uid):
    c = app.test_client()
    with c.session_transaction(base_url=BASE) as s:
        s['wallet'] = wallet
        s['user_id'] = uid
        s['csrf_token'] = CSRF
    return c

def post_notifications(uid):
    with sqlite3.connect(d.DB_FILE) as conn:
        return conn.execute(
            "SELECT id,type,link FROM notifications WHERE user_id=? AND type='follow_post' ORDER BY id",
            (uid,)
        ).fetchall()

author_wallet, author_uid = member('alice')
reader_wallet, reader_uid = member('bob')
author = client(author_wallet, author_uid)

with sqlite3.connect(d.DB_FILE) as conn:
    conn.execute(
        "INSERT INTO follows(follower_id,following_id,notify_enabled,created_at) VALUES(?,?,1,CURRENT_TIMESTAMP)",
        (reader_uid, author_uid),
    )

# Two post/delete cycles must leave zero stale alerts.
for i in range(2):
    r = author.post('/api/feed/post', json={'content': f'temporary {i}'}, headers=HEADERS, base_url=BASE)
    assert r.status_code == 200 and r.get_json()['ok']
    pid = r.get_json()['id']
    rows = post_notifications(reader_uid)
    assert rows and rows[-1][2] == f'/#post-p{pid}'
    r = author.post(f'/api/post/{pid}/delete', json={}, headers=HEADERS, base_url=BASE)
    assert r.status_code == 200 and r.get_json()['ok']
    assert post_notifications(reader_uid) == []

# A post that remains published keeps exactly its one notification.
r = author.post('/api/feed/post', json={'content': 'this one stays'}, headers=HEADERS, base_url=BASE)
assert r.status_code == 200 and r.get_json()['ok']
pid = r.get_json()['id']
rows = post_notifications(reader_uid)
assert len(rows) == 1 and rows[0][2] == f'/#post-p{pid}'

src = (ROOT / 'dashboard.py').read_text(encoding='utf-8')
assert "def _delete_post_notifications" in src
assert "_delete_post_notifications(conn, '/#post-p' + str(post_id))" in src
assert "_delete_post_notifications(conn, post_link)" in src

# Direct messages follow the same rule: each notification is tied to the exact
# message id, so deleting that message removes only its own alert.
reader = client(reader_wallet, reader_uid)
for i in range(2):
    r = author.post(f'/api/messages/{reader_uid}', json={'message': f'dm temp {i}'}, headers=HEADERS, base_url=BASE)
    assert r.status_code == 200 and r.get_json()['ok']
    mid = r.get_json()['message_id']
    with sqlite3.connect(d.DB_FILE) as conn:
        row = conn.execute(
            "SELECT link FROM notifications WHERE user_id=? AND type='message' AND actor_wallet=? ORDER BY id DESC LIMIT 1",
            (reader_uid, author_wallet),
        ).fetchone()
    assert row and row[0] == f'/messages/{author_wallet}?mid={mid}'
    r = author.delete(f'/api/messages/{mid}', headers=HEADERS, base_url=BASE)
    assert r.status_code == 200 and r.get_json()['ok']
    with sqlite3.connect(d.DB_FILE) as conn:
        ghost = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id=? AND type='message' AND link=?",
            (reader_uid, f'/messages/{author_wallet}?mid={mid}'),
        ).fetchone()[0]
    assert ghost == 0

r = author.post(f'/api/messages/{reader_uid}', json={'message': 'dm stays'}, headers=HEADERS, base_url=BASE)
mid = r.get_json()['message_id']
with sqlite3.connect(d.DB_FILE) as conn:
    kept = conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id=? AND type='message' AND link=?",
        (reader_uid, f'/messages/{author_wallet}?mid={mid}'),
    ).fetchone()[0]
assert kept == 1
print('PASS deleted/reposted content and deleted DMs leave no ghost notifications; final items keep one')
