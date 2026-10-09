"""Own-message mutations, incremental updates and atomic ownership transfer."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROBE = r'''
import os, sqlite3, threading
from cryptography.fernet import Fernet
os.environ['ENCRYPTION_KEY']=Fernet.generate_key().decode()
original_thread_start=threading.Thread.start
threading.Thread.start=lambda self:None
import app_entry
threading.Thread.start=original_thread_start
from flask import session
app=app_entry.app;d=app_entry._dashboard;app.testing=True
d._send_push_notifications_bulk=lambda *a,**k:None
d._rate_ok=lambda *a,**k:True
base='https://orcagent.fun';headers={'X-CSRF-Token':'x'*40,'Origin':base}
wallets=['11111111111111111111111111111111','So11111111111111111111111111111111111111112','Cdn8WftaYycdudV9yeeQPY1A1Tgo1bMa9eV4Tv9SeAM9']
uids=[d.get_or_create_user(w) for w in wallets]
with sqlite3.connect(d.DB_FILE) as db:
 for uid,name in zip(uids,['alice','bob','outsider']):
  db.execute('UPDATE users SET username=? WHERE id=?',(name,uid))
  db.execute('INSERT INTO tos_acceptances(user_id,version,accepted_at) VALUES(?,?,datetime())',(uid,d.TOS_VERSION))
 db.execute('INSERT INTO follows(follower_id,following_id) VALUES(?,?)',(uids[0],uids[1]))
clients=[]
for wallet,uid in zip(wallets,uids):
 cl=app.test_client()
 with cl.session_transaction(base_url=base) as s:s.update(wallet=wallet,user_id=uid,csrf_token='x'*40)
 clients.append(cl)
a,b,outside=clients

def req(cl,path,method='GET',body=None,h=headers):
 return cl.open(path,method=method,json=body,headers=h,base_url=base)
created=req(a,'/api/group-chats','POST',{'name':'Test crew','user_ids':[uids[1]]})
assert created.status_code==200,created.json
gid=created.json['chat']['id'];root='/api/group-chats/'+str(gid)
msg=req(a,root+'/messages','POST',{'message':'Original'}).json['message'];mid=msg['id'];path=root+'/messages/'+str(mid)
assert req(a,path,'PUT',{'message':'new'},{}).status_code==403
assert req(b,path,'PUT',{'message':'stolen'}).status_code==403
assert req(b,path,'DELETE').status_code==403
assert req(outside,path,'DELETE').status_code==404
assert req(app.test_client(),path,'DELETE').status_code==401
assert req(a,path,'PUT',{'message':' '}).status_code==400
assert req(a,path,'PUT',{'message':'x'*1001}).status_code==400
assert req(a,path,'PUT',{'message':'Edited <script>bad()</script> text'}).status_code==200
changes=req(b,root+'/messages?after='+str(mid)+'&changes_since=0').json
assert changes['messages']==[] and len(changes['updates'])==1,changes
updated=changes['updates'][0]
assert updated['edited_at'] and '<script>' not in updated['body'] and updated['id']==mid
version=changes['change_version']
assert req(b,root+'/messages?after='+str(mid)+'&changes_since='+str(version)).json['updates']==[]
assert req(a,path,'PUT',{'message':'Second rapid edit'}).status_code==200
rapid=req(b,root+'/messages?after='+str(mid)+'&changes_since='+str(version)).json
assert rapid['updates'][0]['body']=='Second rapid edit' and rapid['change_version']>version
version=rapid['change_version']
assert req(a,path,'DELETE').status_code==200
changes=req(b,root+'/messages?after='+str(mid)+'&changes_since='+str(version)).json
assert changes['updates'][0]['kind']=='deleted' and changes['updates'][0]['body']==''
assert req(a,path,'DELETE').status_code==200
assert req(a,path,'PUT',{'message':'restore'}).status_code==409
assert req(b,'/api/messages/unread_count').json['count']==0
with sqlite3.connect(d.DB_FILE) as db:
 sysid=db.execute("SELECT id FROM group_chat_messages WHERE chat_id=? AND kind='system' LIMIT 1",(gid,)).fetchone()[0]
 photoid=db.execute("INSERT INTO group_chat_messages(chat_id,sender_id,kind,body,created_at) VALUES(?,?,'image','photo',datetime())",(gid,uids[0])).lastrowid
assert req(a,root+'/messages/'+str(sysid),'DELETE').status_code==403
assert req(a,root+'/messages/'+str(photoid),'PUT',{'message':'text'}).status_code==400
assert req(a,root+'/messages/'+str(photoid),'DELETE').status_code==200
other=req(a,'/api/group-chats','POST',{'name':'Other','user_ids':[uids[1]]}).json['chat']['id']
assert req(a,'/api/group-chats/'+str(other)+'/messages/'+str(mid),'DELETE').status_code==404
assert req(b,root+'/owner','POST',{'user_id':uids[0]}).status_code==403
assert req(a,root+'/owner','POST',{'user_id':uids[2]}).status_code==404
assert req(a,root+'/owner','POST',{'user_id':uids[1]},{}).status_code==403
transfer=req(a,root+'/owner','POST',{'user_id':uids[1]})
assert transfer.status_code==200,transfer.json
assert not transfer.json['chat']['is_owner'] and transfer.json['chat']['role']=='admin'
info=req(b,root).json['chat']
assert info['is_owner'] and sum(m['owner'] for m in info['members'])==1
assert req(a,root+'/owner','POST',{'user_id':uids[0]}).status_code==403
assert req(a,root,'DELETE').status_code==403
assert any('transferred ownership to bob' in m['body'] for m in req(b,root+'/messages').json['messages'])
import concurrent.futures
third=req(a,'/api/group-chats','POST',{'name':'Atomic crew','user_ids':[uids[1]]}).json['chat']['id']
def transfer_once(_):
 cl=app.test_client()
 with cl.session_transaction(base_url=base) as s:s.update(wallet=wallets[0],user_id=uids[0],csrf_token='x'*40)
 return req(cl,'/api/group-chats/'+str(third)+'/owner','POST',{'user_id':uids[1]}).status_code
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
 assert sorted(pool.map(transfer_once,range(2)))==[200,403]
print('GROUP_MESSAGE_MANAGEMENT_PASS')
'''

class GroupMessageManagement(unittest.TestCase):
    def test_production_auth_mutations_updates_and_owner_transfer(self):
        with tempfile.TemporaryDirectory() as data:
            env={**os.environ,'DATA_DIR':data,'PYTHONPATH':str(Path(__file__).resolve().parents[1])}
            run=subprocess.run([sys.executable,'-c',PROBE],env=env,capture_output=True,text=True,timeout=90)
            self.assertEqual(run.returncode,0,run.stdout[-2000:]+run.stderr[-2000:])
            self.assertIn('GROUP_MESSAGE_MANAGEMENT_PASS',run.stdout)
