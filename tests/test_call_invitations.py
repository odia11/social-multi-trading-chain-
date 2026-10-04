"""First proven signups, immutable invitation attribution and confirmed totals."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import call_invitations as inv

ROOT=Path(__file__).resolve().parents[1]
MINT='So11111111111111111111111111111111111111112'
TOKEN='A'*24

PROBE=r'''
import contextlib,io,threading,sqlite3
threading.Thread.start=lambda self:None
with contextlib.redirect_stdout(io.StringIO()):import app_entry as entry
d=entry._dashboard;d.app.config['TESTING']=True
from solders.keypair import Keypair
from trader_rewards import record_confirmed_trade
kp=Keypair();wallet=str(kp.pubkey());origin='https://orcagent.fun'
with sqlite3.connect(d.DB_FILE) as c:
 c.execute("INSERT INTO users(wallet_address,username,referral_code) VALUES('actor','<script>alert(1)</script>','ACTOR234')")
 actor=c.execute("SELECT id FROM users WHERE wallet_address='actor'").fetchone()[0]
 c.execute("INSERT INTO users(wallet_address,username,referral_code) VALUES('other','other','OTHER234')")
 c.execute("INSERT INTO users(wallet_address,username) VALUES('old','existing')")
 c.execute("INSERT INTO token_calls(wallet,peak_price,user_id,mint,symbol,note,price_at_call,chain) VALUES('actor',1,?,?,?,?,?,?)",(actor,'So11111111111111111111111111111111111111112','TEST','<img src=x onerror=alert(1)>',1,'solana'))
 call=c.execute('SELECT MAX(id) FROM token_calls').fetchone()[0]
 c.execute("INSERT INTO token_calls(wallet,peak_price,user_id,mint,symbol,price_at_call,chain) VALUES('actor',1,?,?,?,?,?)",(actor,'0x123','EVM',1,'base'))
 evm=c.execute('SELECT MAX(id) FROM token_calls').fetchone()[0]
client=d.app.test_client()
with client.session_transaction(base_url=origin) as s:s.update(wallet='actor',csrf_token='x'*40)
h={'Origin':origin,'X-CSRF-Token':'x'*40}
def get(c,path):return c.get(path,base_url=origin)
def post(c,path,body=None,headers=h):return c.post(path,json=body,headers=headers,base_url=origin)
assert post(client,f'/api/calls/{call}/share',headers={}).status_code==403
shared=post(client,f'/api/calls/{call}/share').json;assert shared['ok'];url=shared['url'];path=url.replace(origin,'')
assert post(client,f'/api/calls/{call}/share').json['url']==url
assert post(client,f'/api/calls/{evm}/share').status_code==404
assert get(client,'/api/invitations?user_id=999').json['share_links']==1
assert 'no-store' in get(client,'/api/invitations').headers['Cache-Control']
assert get(client,'/invitations').status_code==200
visitor=d.app.test_client()
assert get(visitor,'/api/invitations').status_code==401
assert post(visitor,f'/api/calls/{call}/share').status_code==401
assert get(visitor,'/invitations').status_code==302
page=get(visitor,path);assert page.status_code==200
assert '<script>alert(1)</script>' not in page.text and '&lt;script&gt;' in page.text
assert '<img src=x onerror' not in page.text and '&lt;img' in page.text
assert '/live-market?mint=So11111111111111111111111111111111111111112' in page.text
assert f'/u/{actor}' in page.text and 'og:image' in page.text and f'/call/{call}' in page.text
assert any('orca_invite=' in value and 'HttpOnly' in value and 'Secure' in value for value in page.headers.getlist('Set-Cookie'))
# A later valid invitation cannot overwrite the first one.
get(visitor,'/?ref=OTHER234')
assert get(client,'/api/invitations').json['signups']==0
assert get(visitor,'/api/invitations/return').json=={'ok':True,'pending':False,'path':None}
get(visitor,'/?call_return='+str(call))
assert get(visitor,'/api/invitations/return').json['pending']
# Read-only address entry creates no credited signup, even with a forged code.
r=post(visitor,'/api/wallet/connect-readonly',{'address':wallet,'ref_code':'OTHER234'});assert r.status_code==200,(r.status_code,r.json)
assert get(client,'/api/invitations').json['signups']==0
with sqlite3.connect(d.DB_FILE) as c:
 uid=c.execute('SELECT id FROM users WHERE wallet_address=?',(wallet,)).fetchone()[0]
 assert c.execute('SELECT referred_by FROM users WHERE id=?',(uid,)).fetchone()[0] is None
 assert c.execute('SELECT pending_json FROM invitation_accounts WHERE user_id=?',(uid,)).fetchone()[0] is None
# Sign an actual fresh nonce with a synthetic key; no on-chain transaction.
nonce=get(visitor,'/api/auth/nonce').json
signature=str(kp.sign_message(nonce['message'].encode()))
r=post(visitor,'/api/wallet/set',{'address':wallet,'nonce':nonce['nonce'],'signature':signature,'ref_code':'OTHER234'});assert r.status_code==200,(r.status_code,r.json)
assert get(visitor,'/api/invitations/return').json['path']==f'/call/{call}'
get(visitor,f'/call/{call}');assert not get(visitor,'/api/invitations/return').json['pending']
assert get(client,'/api/invitations').json['signups']==1
with sqlite3.connect(d.DB_FILE) as c:
 uid=c.execute('SELECT id FROM users WHERE wallet_address=?',(wallet,)).fetchone()[0]
 assert c.execute('SELECT referred_by FROM users WHERE id=?',(uid,)).fetchone()[0]=='actor'
# Returning users and owner-forged API params cannot change attribution.
get(visitor,'/?ref=OTHER234');get(visitor,'/api/session')
assert get(client,'/api/invitations').json['signups']==1
assert record_confirmed_trade(d.DB_FILE,wallet,'3'*88,'So11111111111111111111111111111111111111112','buy',10,'USDC',0)
assert not record_confirmed_trade(d.DB_FILE,wallet,'3'*88,'So11111111111111111111111111111111111111112','buy',10,'USDC',0)
assert not record_confirmed_trade(d.DB_FILE,wallet,'4'*88,'x','buy',0.5,'USDC',0)
m=get(client,'/api/invitations').json;assert (m['signups'],m['traders'],m['trades'],m['volume_usdc'])==(1,1,1,10.0),m
assert not any(key in str(m) for key in ('balance','private_key',wallet))
image=get(visitor,f'/api/call-card/{call}.png?via='+url.split('via=')[1]);assert image.status_code==200 and image.data.startswith(b'\x89PNG')
assert 'X-Robots-Tag' not in image.headers
from PIL import Image
assert Image.open(io.BytesIO(image.data)).size==(1200,630)
assert get(visitor,f'/call/{evm}').status_code==404
assert get(visitor,'/call/999999999').status_code==404
old=d.app.test_client();get(old,path)
with old.session_transaction(base_url=origin) as s:s.update(wallet='old',csrf_token='x'*40)
get(old,'/api/session')
with sqlite3.connect(d.DB_FILE) as c:assert c.execute("SELECT referred_by FROM users WHERE wallet_address='old'").fetchone()[0] is None
assert get(client,'/api/invitations').json['signups']==1
# Deleted calls invalidate preview/share links; old invitation metrics remain.
with sqlite3.connect(d.DB_FILE) as c:c.execute('DELETE FROM token_calls WHERE id=?',(call,))
assert get(visitor,path).status_code==404
print('CALL_INVITATIONS_WSGI_PASS')
'''


class Invitations(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=str(Path(self.tmp.name)/'db')
        with sqlite3.connect(self.db) as c:
            c.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY,wallet_address TEXT,username TEXT,referred_by TEXT,referral_code TEXT,is_verified INTEGER DEFAULT 0);
            CREATE TABLE token_calls(id INTEGER PRIMARY KEY,user_id INTEGER,mint TEXT,symbol TEXT,note TEXT,price_at_call REAL,timestamp TEXT,post_id INTEGER,chain TEXT);
            CREATE TABLE reward_trades(signature TEXT PRIMARY KEY,user_id INTEGER,volume_usdc REAL,executed_at REAL,eligibility TEXT,side TEXT);
            INSERT INTO users(id,wallet_address,username,referred_by,referral_code) VALUES(1,'actor','actor',NULL,'ACTOR234');
            INSERT INTO users(id,wallet_address,username,referred_by,referral_code) VALUES(2,'visitor','visitor',NULL,NULL);
            INSERT INTO users(id,wallet_address,username,referred_by,referral_code) VALUES(3,'other','other',NULL,'OTHER234');''')
        inv.initialize(self.db)
        with sqlite3.connect(self.db) as c:
            c.execute('INSERT INTO token_calls VALUES(1,1,?,?,?,1,?,NULL,?)',(MINT,'TEST','analysis','2026-10-04 16:00:00','solana'))
            c.execute('INSERT INTO call_share_links VALUES(?,?,?,?)',(TOKEN,1,1,100))
            c.execute('INSERT INTO invitation_accounts(user_id,created_at) VALUES(2,100)')
        self.invite=dict(referrer_id=1,share_token=TOKEN,call_id=1)

    def tearDown(self):self.tmp.cleanup()

    def test_first_proven_signup_is_immutable_and_not_self(self):
        self.assertFalse(inv.complete_signup(self.db,1,self.invite,101)) # existing owner
        self.assertTrue(inv.complete_signup(self.db,2,self.invite,101))
        self.assertFalse(inv.complete_signup(self.db,2,dict(referrer_id=3),102))
        with sqlite3.connect(self.db) as c:self.assertEqual(c.execute('SELECT referred_by FROM users WHERE id=2').fetchone()[0],'actor')
        self.assertEqual(inv.metrics(self.db,1)['signups'],1)
        self.assertEqual(inv.metrics(self.db,3)['signups'],0)

    def test_first_login_without_invite_closes_attribution(self):
        self.assertFalse(inv.complete_signup(self.db,2,None,101))
        self.assertFalse(inv.complete_signup(self.db,2,self.invite,102))

    def test_expired_and_self_invites_never_count(self):
        self.assertFalse(inv.complete_signup(self.db,2,self.invite,100+inv.WINDOW+1))
        with sqlite3.connect(self.db) as c:c.execute('UPDATE invitation_accounts SET verified_at=NULL WHERE user_id=2')
        self.assertFalse(inv.complete_signup(self.db,2,dict(referrer_id=2),101))
        self.assertEqual(inv.metrics(self.db,1)['signups'],0)

    def test_only_eligible_confirmed_trades_after_signup_count(self):
        inv.complete_signup(self.db,2,self.invite,101)
        with sqlite3.connect(self.db) as c:
            c.executemany('INSERT INTO reward_trades VALUES(?,?,?,?,?,?)',[
                ('a',2,10,102,'eligible','buy'),('b',2,4,103,'eligible','sell'),
                ('c',2,100,90,'eligible','buy'),('d',2,30,104,'review','buy'),
                ('e',2,0.5,104,'eligible','buy'),('f',3,20,104,'eligible','buy'),
                ('g',2,40,104,'excluded','sell'),('h',2,50,104,'eligible','tip')])
        metrics=inv.metrics(self.db,1)
        self.assertEqual((metrics['traders'],metrics['trades'],metrics['volume_usdc']),(1,2,14))
        self.assertEqual(metrics['shares'][0]['signups'],1)
        self.assertFalse(any(key in str(metrics) for key in ('balance','visitor','signature')))

    def test_lookup_filters_other_chains_deleted_calls_and_invalid_codes(self):
        with sqlite3.connect(self.db) as c:
            self.assertEqual(inv.resolve_invite(c,token=TOKEN)['referrer_id'],1)
            self.assertIsNone(inv.resolve_invite(c,code="' OR 1=1 --"))
            self.assertIsNone(inv.resolve_invite(c,token='A'*23))
            c.execute("UPDATE token_calls SET chain='base' WHERE id=1")
            self.assertIsNone(inv.resolve_invite(c,token=TOKEN))
        self.assertIsNone(inv.public_call(self.db,1))

    @unittest.skipUnless(importlib.util.find_spec('flask') and importlib.util.find_spec('solders'),'Full app dependencies required')
    def test_actual_wsgi_signed_login_private_metrics_share_and_card(self):
        from cryptography.fernet import Fernet
        import secrets
        with tempfile.TemporaryDirectory() as tmp:
            env=dict(os.environ,DATA_DIR=tmp,ENCRYPTION_KEY=Fernet.generate_key().decode(),SECRET_KEY=secrets.token_urlsafe(48),ORCAGENT_PRICE_ALERTS='0',ORCAGENT_TRENDING_ALERTS='0')
            r=subprocess.run([sys.executable,'-c',PROBE],cwd=ROOT,env=env,capture_output=True,text=True,timeout=90)
        self.assertEqual(r.returncode,0,r.stdout[-3000:]+'\n'+r.stderr[-3000:])
        self.assertIn('CALL_INVITATIONS_WSGI_PASS',r.stdout)


if __name__=='__main__':unittest.main()
