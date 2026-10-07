"""Authenticated replies, mentions and assistant notifications point to the exact reply."""
import os, sqlite3, tempfile, threading, secrets
from pathlib import Path
from cryptography.fernet import Fernet
os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix='orca-reply-targets-'),ENCRYPTION_KEY=Fernet.generate_key().decode(),SECRET_KEY=secrets.token_urlsafe(48),ORCAGENT_PRICE_ALERTS='0',ORCAGENT_TRENDING_ALERTS='0')
start=threading.Thread.start
threading.Thread.start=lambda self:None
try:
    import app_entry
finally:
    threading.Thread.start=start
from solders.keypair import Keypair
d=app_entry._dashboard
d._send_push_notification=lambda *a,**k:None
wallets=[str(Keypair().pubkey()) for _ in range(4)]
ids=[d.get_or_create_user(w) for w in wallets]
with sqlite3.connect(d.DB_FILE) as c:
    for uid,name in zip(ids,['Owner','Writer','Tagged','Orcagent']):
        c.execute('UPDATE users SET username=?,is_verified=? WHERE id=?',(name,int(name=='Orcagent'),uid))
    post=c.execute("INSERT INTO feed_posts(wallet,content,created_at) VALUES(?,?,'2026-10-04 00:00:00')",(wallets[0],'Test post')).lastrowid
base='https://orcagent.fun'
client=d.app.test_client()
with client.session_transaction(base_url=base) as s:
    s.update(wallet=wallets[1],user_id=ids[1],csrf_token='reply-test')
headers={'X-CSRF-Token':'reply-test'}
pid='p'+str(post)
result=client.post('/api/feed/reply',json={'post_id':pid,'message':'Hello @Tagged'},headers=headers,base_url=base)
assert result.status_code==200,result.data
rid=result.get_json()['id']
with sqlite3.connect(d.DB_FILE) as c:
    alerts=c.execute('SELECT user_id,type,link FROM notifications').fetchall()
    assert (ids[0],'reply',f'/#post-{pid}-reply-{rid}') in alerts
    assert (ids[2],'mention',f'/#post-{pid}-reply-{rid}') in alerts
nested=client.post('/api/feed/reply',json={'post_id':pid,'parent_reply_id':rid,'message':'What are the fees ? @orcagent'},headers=headers,base_url=base)
assert nested.status_code==200,nested.data
bot=nested.get_json().get('platform_reply_id')
assert bot,'explicit platform tag must produce a reply'
with sqlite3.connect(d.DB_FILE) as c:
    message=c.execute('SELECT message FROM feed_replies WHERE id=?',(bot,)).fetchone()[0]
    assert 'platform fee' in message   # the reviewed fees answer
    assert c.execute('SELECT 1 FROM notifications WHERE user_id=? AND link=?',(ids[1],f'/#post-{pid}-reply-{bot}')).fetchone()
    c.execute("INSERT INTO notifications(user_id,type,content,link) VALUES(?,'reply','Other post','/#post-p999-reply-1')",(ids[0],))
    d._delete_post_notifications(c,'/#post-'+pid)
    assert not c.execute('SELECT 1 FROM notifications WHERE link LIKE ?',('/#post-'+pid+'%',)).fetchone()
    assert c.execute("SELECT 1 FROM notifications WHERE link='/#post-p999-reply-1'").fetchone()
search=client.get('/api/users/search?q=orcagent',base_url=base).get_json()
assert any(u['username']=='Orcagent' for u in search['users'])
print('PASS authenticated reply/mention exact links, nested assistant fees answer/link, lifecycle cleanup, tag search')
