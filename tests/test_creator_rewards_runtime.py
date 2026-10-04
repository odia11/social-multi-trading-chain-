"""Actual Flask pilot routes and execution hook, using synthetic fills only."""
import os
import secrets
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
PROBE=r"""
import contextlib,io,os,sqlite3,threading,time
from types import SimpleNamespace
from solders.keypair import Keypair
creator=str(Keypair().pubkey());buyer=str(Keypair().pubkey());admin=str(Keypair().pubkey())
os.environ['OWNER_WALLET']=admin
threading.Thread.start=lambda self:None
with contextlib.redirect_stdout(io.StringIO()):import app_entry
d=app_entry._dashboard
d.app.config['TESTING']=True
mint='So11111111111111111111111111111111111111112'
with sqlite3.connect(d.DB_FILE) as c:
 for wallet,name in [(creator,'<script>creator</script>'),(buyer,'Buyer'),(admin,'Admin')]:
  c.execute('INSERT INTO users(wallet_address,username,encrypted_private_key) VALUES(?,?,?)',(wallet,name,'ENC'))
 ids={r[0]:r[1] for r in c.execute('SELECT wallet_address,id FROM users')}
 c.execute("INSERT INTO token_calls(wallet,peak_price,user_id,mint,symbol,note,price_at_call,chain) VALUES(?,1,?,?,?,'analysis',1,'solana')",(creator,ids[creator],mint,'SOL'))
 call=c.execute('SELECT MAX(id) FROM token_calls').fetchone()[0]
origin='https://orcagent.fun'
def client(wallet=None):
 c=d.app.test_client()
 if wallet:
  with c.session_transaction(base_url=origin) as s:s.update(wallet=wallet,csrf_token='x'*40)
 return c
headers={'Origin':origin,'X-CSRF-Token':'x'*40}
def get(c,path):return c.get(path,base_url=origin)
def post(c,path,data={},h=headers):return c.post(path,json=data,headers=h,base_url=origin)
guest=client();maker=client(creator);trader=client(buyer);operator=client(admin)
assert get(guest,'/api/creator-rewards').status_code==401
assert post(guest,'/api/creator-rewards/apply').status_code==401
assert post(maker,'/api/creator-rewards/apply',h={}).status_code==403
assert post(maker,'/api/creator-rewards/apply').status_code==200
assert get(maker,'/api/creator-rewards').json['status']=='applied'
assert post(maker,'/api/admin/creator-rewards/member',dict(user_id=ids[creator],status='approved')).status_code==403
assert 'creator_context=' not in get(trader,f'/call/{call}/trade').location
assert post(operator,'/api/admin/creator-rewards/member',dict(user_id=ids[creator],status='approved')).status_code==200
link=get(trader,f'/call/{call}/trade').location
from urllib.parse import parse_qs,urlparse
token=parse_qs(urlparse(link).query)['creator_context'][0]
assert get(maker,'/creator-rewards').status_code==200
assert 'no-store' in get(maker,'/creator-rewards').headers['Cache-Control']
page=get(operator,'/admin/creator-rewards')
assert page.status_code==200,page.text[:300]
assert '<script>creator</script>' not in page.text
assert get(trader,'/api/creator-rewards?user_id='+str(ids[creator])).json['status']=='not_enrolled'
assert d.app._orca_creator_context(buyer,mint,token)['creator_id']==ids[creator]
assert d.app._orca_creator_context(creator,mint,token) is None
assert d.app._orca_creator_context(buyer,'wrong-mint',token) is None
assert d.app._orca_creator_context(buyer,mint,token+'tamper') is None
from unittest.mock import patch
with patch('itsdangerous.timed.time.time',return_value=time.time()+1801):
 assert d.app._orca_creator_context(buyer,mint,token) is None
# Exercise the real subprocess-output parser, fee writer and creator hook.
d._get_trading_wallet_address=lambda wallet:wallet
d._get_user_sol=lambda wallet:10
d.fetch_user_balances=lambda wallet:None
d._sol_price_usd=100
d._dex_get=lambda *a,**kw:None
d._ensure_solana_gas=lambda *a,**kw:(True,'')
d.add_user_log=lambda *a,**kw:None
d._trigger_copy_buy=lambda *a,**kw:None
d._trigger_copy_sell=lambda *a,**kw:None
d._register_manual_buy=lambda *a,**kw:None
d._reduce_after_manual_sell=lambda *a,**kw:None
d.get_user_state=lambda wallet:dict(sol=10,positions={})
class Key:
 def __enter__(self):return 'FAKE'
 def __exit__(self,*args):return False
d._use_key=lambda *args:Key()
state={'signature':'3'*88,'confirmation':'confirmed','bundled':True}
def execute(*args,**kwargs):
 assert args[0][-1]=='SOL'
 marker='[fee] buy: requesting quote' if state['bundled'] else ''
 out=marker+'\n[fee] buy with bundled fee SUCCESS (confirmation='+state['confirmation']+', confirm_time=1s)\n'
 out+='BUY '+mint+' 0.05 SOL got:100 sol:0.05 fee_base:0.05 TX:'+state['signature']
 return SimpleNamespace(returncode=0,stdout=out,stderr='')
d.subprocess.run=execute
body=dict(symbol='SOL',token_address=mint,side='buy',currency='SOL',amount_sol=.05,max_platform_fee_bps=75,creator_context=token)
reply=post(trader,'/api/instant-trade',body)
assert reply.status_code==200,(reply.status_code,reply.json)
j=get(maker,'/api/creator-rewards').json
assert len(j['rewards'])==1 and j['totals']['pending_sol']==37500,j
assert j['totals']['available']==0
assert get(trader,'/api/creator-rewards').json['rewards']==[]
with sqlite3.connect(d.DB_FILE) as c:
 fee=c.execute('SELECT fee_amount,fee_tx FROM fees WHERE fee_tx=?',('bundled:'+state['signature'],)).fetchone()
 assert fee==(.000375,'bundled:'+state['signature']),fee
for signature,confirmation,bundled,context in [
 ('6'*88,'confirmed',True,token+'tamper'),
 ('7'*88,'timeout',True,token),
 ('8'*88,'confirmed',False,token)]:
 state.update(signature=signature,confirmation=confirmation,bundled=bundled)
 d._recent_solana_buys.clear()
 body['creator_context']=context
 reply=post(trader,'/api/instant-trade',body)
 assert reply.status_code==200,(reply.status_code,reply.json)
assert len(get(maker,'/api/creator-rewards').json['rewards'])==1
assert post(maker,'/api/creator-rewards/payout').status_code==409
assert post(operator,'/api/admin/creator-rewards/paid',dict(payout_id='bad',signature='bad')).status_code==409
print('CREATOR_PILOT_WSGI_EXECUTION_PASS')
"""


class Runtime(unittest.TestCase):
    def test_authenticated_pilot_routes_and_real_fee_hook(self):
        from cryptography.fernet import Fernet
        with tempfile.TemporaryDirectory() as tmp:
            env=dict(os.environ,DATA_DIR=tmp,ENCRYPTION_KEY=Fernet.generate_key().decode(),
                     SECRET_KEY=secrets.token_urlsafe(48),ORCAGENT_PRICE_ALERTS='0',ORCAGENT_TRENDING_ALERTS='0')
            r=subprocess.run([sys.executable,'-c',PROBE],cwd=ROOT,env=env,capture_output=True,text=True,timeout=90)
        self.assertEqual(r.returncode,0,r.stdout[-3000:]+'\n'+r.stderr[-3000:])
        self.assertIn('CREATOR_PILOT_WSGI_EXECUTION_PASS',r.stdout)


if __name__=='__main__':unittest.main()
