"""Opt-in follower delivery, private preferences, and real call publication routes."""
import ast
import importlib.util
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import following_traders as f

ROOT=Path(__file__).resolve().parents[1]
MINT='So11111111111111111111111111111111111111112'

PROBE=r'''
import contextlib,io,threading,sqlite3
threading.Thread.start=lambda self:None
with contextlib.redirect_stdout(io.StringIO()):import app_entry as entry
d=entry._dashboard;d.app.config['TESTING']=True
mint='So11111111111111111111111111111111111111112'
with sqlite3.connect(d.DB_FILE) as c:
 for name in ['actor','reader','all','muted','globaloff','stranger']:
  c.execute('INSERT INTO users(wallet_address,username,pref_notifications) VALUES(?,?,?)',(name,name,0 if name=='globaloff' else 1))
 ids=dict(c.execute('SELECT wallet_address,id FROM users'))
 for name,mode,enabled in [('reader','calls',1),('all','all',1),('muted','all',0),('globaloff','all',1)]:
  c.execute('INSERT INTO follows(follower_id,following_id,notify_enabled,notify_mode) VALUES(?,?,?,?)',(ids[name],ids['actor'],enabled,mode))
viewer=['reader'];d._authenticated_wallet=lambda:viewer[0]
d.get_token_data=lambda *a,**kw:{'price':1,'symbol':'TEST','name':'Test token'}
d._dex_get=lambda *a,**kw:None
push=[];d._send_push_notifications_bulk=lambda recipients,*a,**kw:push.append((recipients,a))
d._send_push_notification=lambda *a,**kw:None
client=d.app.test_client()
with client.session_transaction(base_url='https://orcagent.fun') as s:s.update(wallet='reader',csrf_token='x'*40)
h={'Origin':'https://orcagent.fun','X-CSRF-Token':'x'*40}
def get(path):return client.get(path,base_url='https://orcagent.fun')
def put(mode,**extra):return client.put('/api/following/preferences/'+str(ids['actor']),json=dict(mode=mode,**extra),headers=h,base_url='https://orcagent.fun')
page=get('/following');assert page.status_code==302 and page.location.endswith('/')
prefs=get('/api/following/preferences');assert prefs.status_code==200 and prefs.json['traders'][0]['mode']=='calls'
assert 'no-store' in prefs.headers['Cache-Control'] and 'private' in prefs.headers['Cache-Control']
assert not any('balance' in key for key in prefs.json['traders'][0])
assert client.put('/api/following/preferences/'+str(ids['actor']),json={'mode':'all'},base_url='https://orcagent.fun').status_code==403
assert put([]).status_code==400
assert put('calls',follower_id=ids['all']).status_code==200
assert put('calls').status_code==200
assert get('/api/following/preferences?before=bad').status_code==400
viewer[0]='stranger';assert get('/api/following/preferences?user_id='+str(ids['reader'])).json['traders']==[]
assert put('all').status_code==404
viewer[0]=None;assert get('/api/following/calls').status_code==401 and get('/api/following/preferences').status_code==401
viewer[0]='actor'
for feed in (False,True):
 response=client.post('/api/calls',json={'mint':mint,'post_to_feed':feed,'note':'Analysis'},headers=h,base_url='https://orcagent.fun')
 assert response.status_code==200,(response.status_code,response.json)
 expected='/#post-p'+str(response.json['post_id']) if feed else '/live-market?mint='+mint
 with sqlite3.connect(d.DB_FILE) as c:
  rows=c.execute('SELECT user_id,link FROM notifications WHERE type="follow_call" AND link=?',(expected,)).fetchall()
 assert sorted(r[0] for r in rows)==sorted([ids['reader'],ids['all']]),rows
 assert sorted(push[-1][0])==sorted([ids['reader'],ids['all']])
viewer[0]='reader';calls=get('/api/following/calls').json['calls'];assert len(calls)==2 and calls[0]['mint']==mint
assert put('off').status_code==200
viewer[0]='actor'
response=client.post('/api/calls',json={'mint':mint},headers=h,base_url='https://orcagent.fun');assert response.status_code==200
assert push[-1][0]==[ids['all']]
with sqlite3.connect(d.DB_FILE) as c:c.execute('DELETE FROM follows WHERE follower_id=?',(ids['reader'],))
viewer[0]='reader';assert get('/api/following/calls').json['calls']==[]
print('FOLLOWING_WSGI_AUTH_PREFS_CALL_NOTIFICATIONS_PASS')
'''


class Following(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=str(Path(self.tmp.name)/'test.db')
        with sqlite3.connect(self.db) as c:
            c.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,wallet_address TEXT,is_verified INTEGER,pref_notifications INTEGER);
            CREATE TABLE follows(follower_id INTEGER,following_id INTEGER,notify_enabled INTEGER DEFAULT 0,UNIQUE(follower_id,following_id));
            CREATE TABLE token_calls(id INTEGER PRIMARY KEY,user_id INTEGER,mint TEXT,symbol TEXT,note TEXT,post_id INTEGER,timestamp TEXT,price_at_call REAL,chain TEXT);
            CREATE TABLE notifications(id INTEGER PRIMARY KEY,user_id INTEGER,type TEXT,content TEXT,link TEXT,actor_wallet TEXT);''')
            c.executemany('INSERT INTO users VALUES(?,?,?,?,?)',[(1,'reader','reader',0,1),(2,'actor','actor',1,1),(3,'all','all',0,1),(4,'muted','muted',0,1),(5,'globaloff','globaloff',0,0)])
            c.executemany('INSERT INTO follows VALUES(?,?,?)',[(1,2,1),(3,2,1),(4,2,0),(5,2,1)])
        f.initialize(self.db)

    def tearDown(self):self.tmp.cleanup()

    def test_migration_keeps_existing_opt_in(self):
        f.initialize(self.db)
        self.assertEqual(f.preferences(self.db,1)['traders'][0]['mode'],'all')
        self.assertEqual(f.preferences(self.db,4)['traders'][0]['mode'],'off')
        self.assertFalse(f.preferences(self.db,5)['notifications_enabled'])

    def test_own_preferences_idempotency_and_validation(self):
        self.assertTrue(f.set_preference(self.db,1,2,'calls'))
        self.assertTrue(f.set_preference(self.db,1,2,'calls'))
        self.assertFalse(f.set_preference(self.db,2,1,'all'))
        self.assertEqual(f.preferences(self.db,3)['traders'][0]['mode'],'all')
        for value in (None,True,{},[],'bogus'):
            with self.assertRaises(ValueError):f.set_preference(self.db,1,2,value)
        self.assertTrue(f.set_preference(self.db,1,2,'off'))
        self.assertEqual(f.preferences(self.db,1)['traders'][0]['mode'],'off')

    def test_preferences_paginate_without_financial_fields(self):
        with sqlite3.connect(self.db) as c:
            for uid in range(10,115):
                c.execute('INSERT INTO users VALUES(?,?,?,0,1)',(uid,'name'+str(uid),'wallet'+str(uid)))
                c.execute('INSERT INTO follows(follower_id,following_id,notify_enabled) VALUES(1,?,0)',(uid,))
        first=f.preferences(self.db,1);second=f.preferences(self.db,1,first['next_cursor'])
        self.assertEqual(len(first['traders'])+len(second['traders']),106)
        self.assertIsNone(second['next_cursor'])
        self.assertEqual(set(first['traders'][0]),{'user_id','username','wallet','verified','mode'})

    def test_recent_calls_only_followed_solana_and_unfollow_removes(self):
        with sqlite3.connect(self.db) as c:
            c.executemany('INSERT INTO token_calls VALUES(?,?,?,?,?,?,?,?,?)',[(1,2,MINT,'SOL','hello',None,'2026-10-04 15:00:00',100,'solana'),(2,3,MINT,'SOL','other',None,'2026-10-04 15:00:00',100,'solana'),(3,2,'0x123','EVM','old',None,'2026-10-04 15:00:00',100,'base')])
        self.assertEqual([row['id'] for row in f.recent_calls(self.db,1)],[1])
        with sqlite3.connect(self.db) as c:c.execute('DELETE FROM follows WHERE follower_id=1')
        self.assertEqual(f.recent_calls(self.db,1),[])

    def test_notification_dispatch_calls_posts_mute_global_off(self):
        tree=ast.parse((ROOT/'dashboard.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_notify_followers')
        scope={};exec(compile(ast.Module(body=[node],type_ignores=[]),'<followers>','exec'),scope)
        f.set_preference(self.db,1,2,'calls')
        with sqlite3.connect(self.db) as c:
            post=scope['_notify_followers'](c,2,'follow_post',lambda name:name+' post','/#post-p1','actor')
            call=scope['_notify_followers'](c,2,'follow_call',lambda name:name+' call','/live-market?mint='+MINT,'actor',event_kind='call')
        self.assertEqual(post,[3]);self.assertEqual(call,[1,3])

    @unittest.skipUnless(importlib.util.find_spec('flask') and importlib.util.find_spec('requests'),'Full app dependencies required')
    def test_actual_wsgi_preferences_and_call_delivery(self):
        import secrets
        from cryptography.fernet import Fernet
        with tempfile.TemporaryDirectory() as tmp:
            env=dict(os.environ,DATA_DIR=tmp,ENCRYPTION_KEY=Fernet.generate_key().decode(),SECRET_KEY=secrets.token_urlsafe(48),ORCAGENT_PRICE_ALERTS='0',ORCAGENT_TRENDING_ALERTS='0')
            result=subprocess.run([sys.executable,'-c',PROBE],cwd=ROOT,env=env,capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout[-2500:]+'\n'+result.stderr[-2500:])
        self.assertIn('FOLLOWING_WSGI_AUTH_PREFS_CALL_NOTIFICATIONS_PASS',result.stdout)


if __name__=='__main__':unittest.main()
