"""Exercise actual Flask manual execution with fake fills and fresh app database."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

PROBE=r'''
import contextlib,datetime as dt,json,sqlite3,time
import dashboard as d
import trader_rewards as r
r.initialize(d.DB_FILE)
d.app.config['TESTING']=True
wallet='W_PRO_TEST'
with sqlite3.connect(d.DB_FILE) as c:
 c.execute("INSERT INTO users(wallet_address,encrypted_private_key,created_at) VALUES(?,?,datetime('now','-21 days'))",(wallet,'ENC'))
 uid=c.execute('SELECT id FROM users WHERE wallet_address=?',(wallet,)).fetchone()[0]
for i in range(7):
 r.record_confirmed_trade(d.DB_FILE,wallet,str(i+1)*87,'mint'+str(i),'buy',400,'USDC',0,time.time()-i*86400)
assert r.progress(d.DB_FILE,wallet)['status']=='Pro Trader'
d._authenticated_wallet=lambda:wallet
d._get_trading_wallet_address=lambda w:'TRADING_TEST'
d._get_user_sol=lambda w:1.0
d.fetch_user_balances=lambda w:None
d._sol_price_usd=100
d._PROXY_RPCS=[]
d._dex_get=lambda *a,**kw:None
d._record_ip_failure=lambda *a:None
d.add_user_log=lambda *a:None
d._snapshot_entry_risk=lambda *a,**kw:{}
d._trigger_copy_buy=lambda *a,**kw:None
d._trigger_copy_sell=lambda *a,**kw:None
d._register_manual_buy=lambda *a,**kw:None
d._reduce_after_manual_sell=lambda *a,**kw:None
d.get_user_state=lambda w:{'sol':1.0,'positions':{}}
class Key:
 def __enter__(self):return 'FAKE'
 def __exit__(self,*a):return False
d._use_key=lambda *a:Key()
calls=[]
def execute(w,pk,side,mint,amount,base='SOL',capture=None,fee_rate=None,known_sol_balance=None):
 calls.append(fee_rate)
 capture.update(fee_bundled=True,fee_base=.05,fee_rate=fee_rate)
 return True,('8'*86+str(len(calls))), '',20,.05 if side=='buy' else .0993
d._execute_user_swap_ex=execute
client=d.app.test_client()
with client.session_transaction(base_url='https://orcagent.fun') as session:
 session['wallet']=wallet;session['user_id']=uid;session['csrf_token']='x'*40
headers={'X-CSRF-Token':'x'*40,'Origin':'https://orcagent.fun'}
body=dict(symbol='TOKEN',token_address='So11111111111111111111111111111111111111112',side='buy',currency='SOL',amount_sol=.05,max_platform_fee_bps=70)
response=client.post('/api/instant-trade',json=body,headers=headers,base_url='https://orcagent.fun')
assert response.status_code==200,(response.status_code,response.json)
assert response.json['platform_fee_bps']==70
with sqlite3.connect(d.DB_FILE) as c:
 fee=c.execute('SELECT fee_amount FROM fees ORDER BY id DESC LIMIT 1').fetchone()[0]
assert fee==.00035,fee
body.update(side='sell',amount_sol=0,sell_pct=100)
response=client.post('/api/instant-trade',json=body,headers=headers,base_url='https://orcagent.fun')
assert response.status_code==200,(response.status_code,response.json)
with sqlite3.connect(d.DB_FILE) as c:
 fee=c.execute('SELECT fee_amount FROM fees ORDER BY id DESC LIMIT 1').fetchone()[0]
assert fee==.0007,fee
assert calls==[.007,.007],calls
with sqlite3.connect(d.DB_FILE) as c:c.execute("UPDATE reward_trades SET eligibility='excluded'")
response=client.post('/api/instant-trade',json=body,headers=headers,base_url='https://orcagent.fun')
assert response.status_code==409,(response.status_code,response.json)
assert calls==[.007,.007]
body.update(max_platform_fee_bps=75,is_pro=True)
response=client.post('/api/instant-trade',json=body,headers=headers,base_url='https://orcagent.fun')
assert response.status_code==200,(response.status_code,response.json)
assert response.json['platform_fee_bps']==75
assert calls[-1]==.0075
with sqlite3.connect(d.DB_FILE) as c:
 c.execute("UPDATE users SET referred_by='REFERRER' WHERE wallet_address=?",(wallet,))
 c.execute("INSERT INTO users(wallet_address) VALUES('REFERRER')")
# Inline ledger must credit the existing referral share from the discounted fee.
d._charge_txn_fee('FAKE',wallet,uid,'TOKEN',1,'buy',bundled=True,applied_fee_rate=.007)
with sqlite3.connect(d.DB_FILE) as c:
 earned=c.execute("SELECT earned_sol FROM referral_earnings WHERE referred_wallet=? ORDER BY id DESC LIMIT 1",(wallet,)).fetchone()[0]
assert earned==.0014,earned
print('PRO_TRADE_RUNTIME_PASS')
'''


@unittest.skipUnless(importlib.util.find_spec('flask') and importlib.util.find_spec('requests'), 'Full app dependencies required; this test runs in security CI')
class Runtime(unittest.TestCase):
    def test_actual_manual_buy_sell_expiry_and_referral_ledger(self):
        from cryptography.fernet import Fernet
        with tempfile.TemporaryDirectory() as tmp:
            env=dict(os.environ,DATA_DIR=tmp,ENCRYPTION_KEY=Fernet.generate_key().decode())
            result=subprocess.run([sys.executable,'-c',PROBE],cwd=ROOT,env=env,capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout[-3500:]+'\n'+result.stderr[-3500:])
        self.assertIn('PRO_TRADE_RUNTIME_PASS',result.stdout)
