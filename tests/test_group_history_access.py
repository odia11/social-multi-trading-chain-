"""Isolated API regression: join-time history boundaries and pagination."""
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flask import Flask, request
import group_chats

with tempfile.TemporaryDirectory() as temp:
    db = temp + '/groups.db'
    app = Flask(__name__)
    d = SimpleNamespace(app=app, DB_FILE=db, rate_limit=lambda *a: lambda fn: fn,
        _authenticated_wallet=lambda: request.headers.get('X-Test-Wallet'),
        _get_uid=lambda c,w: c.execute('SELECT id FROM users WHERE wallet_address=?',(w,)).fetchone()[0],
        _sanitize=lambda s:s, _DM_REACTION_EMOJIS=['❤️'], _send_push_notifications_bulk=lambda *a:None)
    group_chats.install(d)
    with sqlite3.connect(db) as c:
        c.executescript('CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,wallet_address TEXT,avatar_url TEXT,is_verified INTEGER);CREATE TABLE follows(follower_id INTEGER,following_id INTEGER);CREATE TABLE notifications(user_id INTEGER,type TEXT,content TEXT,link TEXT,actor_wallet TEXT,is_read INTEGER DEFAULT 0);')
        c.executemany('INSERT INTO users VALUES(?,?,?,"",0)', [(i,'user'+str(i),'wallet'+str(i)) for i in range(1,5)])
        c.executemany('INSERT INTO follows VALUES(1,?)', [(2,),(3,),(4,)])
        c.execute("INSERT INTO group_chats(id,name,created_by,created_at) VALUES(1,'History',1,'2026-10-10')")
        c.execute("INSERT INTO group_chat_members(chat_id,user_id,role,joined_at) VALUES(1,1,'admin','2026-10-10')")
        c.executemany("INSERT INTO group_chat_messages(chat_id,sender_id,body,created_at) VALUES(1,1,?,'2026-10-10 04:00:00')", [('Old '+str(i),) for i in range(125)])
    client=app.test_client()
    def call(method,url,user=1,body=None):
        return getattr(client,method)(url,headers={'X-Test-Wallet':'wallet'+str(user)},json=body)
    assert call('put','/api/group-chats/1/history',body={'visible':False}).json['ok']
    assert call('post','/api/group-chats/1/members',body={'user_ids':[2]}).json['ok']
    hidden=call('get','/api/group-chats/1/messages',2).json
    assert all(m['id']>125 for m in hidden['messages']+hidden['updates'])
    assert not hidden['has_more']
    assert call('get','/api/group-chats/1/messages?before=126',2).json['messages']==[]
    assert call('get','/api/group-chats/1/messages/1/likes',2).status_code==404
    assert call('post','/api/group-chats/1/messages/1/likes',2,{'emoji':'❤️'}).status_code==404
    assert call('put','/api/group-chats/1/history',2,{'visible':True}).status_code==403
    assert call('put','/api/group-chats/1/history',body={'visible':'true'}).status_code==400
    assert call('put','/api/group-chats/1/history',body={'visible':True}).json['ok']
    assert call('post','/api/group-chats/1/members',body={'user_ids':[3]}).json['ok']
    latest=call('get','/api/group-chats/1/messages',3).json
    assert len(latest['messages'])==100 and latest['has_more']
    oldest=latest['messages'][0]['id']
    earlier=call('get','/api/group-chats/1/messages?before='+str(oldest),3).json
    assert earlier['messages'][0]['id']==1 and not earlier['has_more']
    assert not ({m['id'] for m in earlier['messages']} & {m['id'] for m in latest['messages']})
    assert all(m['id']>125 for m in call('get','/api/group-chats/1/messages',2).json['messages'])
    assert call('get','/api/group-chats/1/messages',4).status_code==404
    group_chats.initialize(db)
    assert call('get','/api/group-chats/1/messages',3).json['ok']
print('PASS history setting permissions, hidden reads/reactions, future join policy, pagination, idempotent migration')
