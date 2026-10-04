"""Verified quota exemption is owned by the server, including status revocation."""
import ast
import importlib.util
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

PROBE=r'''
import threading,sqlite3
threading.Thread.start=lambda self:None
import dashboard as d
d.app.config['TESTING']=True
mint='So11111111111111111111111111111111111111112'
with sqlite3.connect(d.DB_FILE) as db:
 db.executemany('INSERT INTO users(wallet_address,is_verified) VALUES(?,?)',[('NORMAL',0),('VERIFIED',1)])
 ids=dict(db.execute('SELECT wallet_address,id FROM users'))
 for wallet in ids:
  db.executemany('INSERT INTO token_calls(user_id,wallet,mint,price_at_call,peak_price) VALUES(?,?,?,1,1)',[(ids[wallet],wallet,mint)]*5)
viewer=['NORMAL'];d._authenticated_wallet=lambda:viewer[0]
d.get_token_data=lambda *a,**kw:{'price':1,'symbol':'TEST','name':'TEST'}
d._get_csrf_token=lambda:'x'*40
client=d.app.test_client()
with client.session_transaction(base_url='https://orcagent.fun') as s:s.update(wallet='NORMAL',csrf_token='x'*40)
headers={'Origin':'https://orcagent.fun','X-CSRF-Token':'x'*40}
def post(**extra):return client.post('/api/calls',json=dict(mint=mint,**extra),headers=headers,base_url='https://orcagent.fun')
def mine():return client.get('/api/calls/mine',base_url='https://orcagent.fun').json
assert mine()['calls_per_day']==5 and mine()['calls_left_today']==0
assert post(is_verified=True,user_id=ids['VERIFIED']).status_code==429
viewer[0]='VERIFIED'
assert mine()['calls_unlimited'] is True and mine()['calls_per_day'] is None and mine()['calls_left_today'] is None
response=post()
assert response.status_code==200,(response.status_code,response.json)
assert response.json['calls_unlimited'] is True and response.json['calls_left_today'] is None
with sqlite3.connect(d.DB_FILE) as db:
 db.executemany('INSERT INTO token_calls(user_id,wallet,mint,price_at_call,peak_price) VALUES(?,?,?,1,1)',[(ids['VERIFIED'],'VERIFIED',mint)]*1000)
assert post().status_code==200
with sqlite3.connect(d.DB_FILE) as db:db.execute('UPDATE users SET is_verified=0 WHERE wallet_address="VERIFIED"')
assert mine()['calls_unlimited'] is False and mine()['calls_per_day']==5 and mine()['calls_left_today']==0
assert post(is_verified=True).status_code==429
with sqlite3.connect(d.DB_FILE) as db:db.execute('UPDATE users SET is_verified=1 WHERE wallet_address="NORMAL"')
viewer[0]='NORMAL'
assert post().status_code==200
print('VERIFIED_CALLS_RUNTIME_PASS')
'''


class VerifiedCalls(unittest.TestCase):
    def test_quota_from_database_only(self):
        source=ast.parse((ROOT/'dashboard.py').read_text())
        node=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='_call_daily_limit')
        scope={'CALLS_PER_DAY_LIMIT':5}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<quota>','exec'),scope)
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE users(id INTEGER,is_verified INTEGER)')
            db.executemany('INSERT INTO users VALUES(?,?)',[(1,1),(2,0),(3,None),(4,2)])
            self.assertIsNone(scope['_call_daily_limit'](db,1))
            for uid in (2,3,4,99):self.assertEqual(scope['_call_daily_limit'](db,uid),5)

    @unittest.skipUnless(importlib.util.find_spec('flask') and importlib.util.find_spec('requests'),'Full runtime dependencies required')
    def test_real_call_routes_verified_unverified_forgery_and_revocation(self):
        from cryptography.fernet import Fernet
        with tempfile.TemporaryDirectory() as tmp:
            env=dict(os.environ,DATA_DIR=tmp,ENCRYPTION_KEY=Fernet.generate_key().decode(),ORCAGENT_PRICE_ALERTS='0')
            result=subprocess.run([sys.executable,'-c',PROBE],cwd=ROOT,env=env,capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout[-2000:]+'\n'+result.stderr[-2000:])
        self.assertIn('VERIFIED_CALLS_RUNTIME_PASS',result.stdout)


if __name__=='__main__':unittest.main()
