"""Exercise installed promotions through OrcAgent's production security stack."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

PROBE=r'''
import os,threading,sqlite3
from unittest.mock import patch
from cryptography.fernet import Fernet
os.environ['ENCRYPTION_KEY']=Fernet.generate_key().decode()
threading.Thread.start=lambda self:None
import app_entry
from flask import jsonify,session
app=app_entry.app;d=app_entry._dashboard;app.testing=True
mint='So11111111111111111111111111111111111111112'
wallet='11111111111111111111111111111111'
d._sol_price_usd=100
d._authenticated_wallet=lambda:session.get('wallet')
d._get_trading_wallet_address=lambda w:wallet
app.view_functions['api_token_info']=lambda mint_address:jsonify(ok=True,symbol='TEST',name='Test token',address=mint_address,chain='solana')
client=app.test_client()
with client.session_transaction(base_url='https://orcagent.fun') as s:s.update(wallet=wallet,csrf_token='x'*40)
h={'X-CSRF-Token':'x'*40,'Origin':'https://orcagent.fun'}
def get(path):return client.get(path,base_url='https://orcagent.fun')
def post(path,body,headers=h):return client.post(path,json=body,headers=headers,base_url='https://orcagent.fun')
page=get('/promote');assert page.status_code==200 and 'promo-packages' in page.text
assert post('/api/promote/create',{},{}).status_code==403
body=dict(package='spotlight',token_mint=mint,description='A real promotion',payment_method='trading')
r=post('/api/promote/create',body);assert r.status_code==200,(r.status_code,r.json)
identifier=r.json['promotion_id'];amount=r.json['amount_sol'];assert amount==.25
import sol_native_payments
with patch.object(sol_native_payments,'native_transfer',return_value=('A'*86,amount)) as transfer:
 paid=post(f'/api/promote/{identifier}/pay',{});assert paid.status_code==200,paid.json
 assert transfer.call_args.args[1]==wallet
 assert transfer.call_args.args[2]==d.ADMIN_WALLET
 assert transfer.call_args.args[3]=='0.250005'
 paid2=post(f'/api/promote/{identifier}/pay',{});assert paid2.json['signature']==paid.json['signature']
 assert transfer.call_count==1
with patch('token_promotions.verify_payment',return_value=True):
 d.app._orca_reconcile_promotions()
status=get(f'/api/promote/{identifier}/status');assert status.json['status']=='active',status.json
ad=get('/api/promote/featured?placement=feed').json['promotions'][0]
assert 'wallet' not in ad and 'payer' not in ad and ad['sponsored']
receipt=ad['receipt']
assert post('/api/promote/event',dict(event='view',receipt=receipt)).status_code==200
assert post('/api/promote/event',dict(event='click',receipt=receipt)).status_code==200
stats=get('/api/promote/mine').json['campaigns'][0];assert stats['views']==1 and stats['clicks']==1
assert 'no-store' in get('/api/promote/mine').headers['Cache-Control']
assert post(f'/api/promote/{identifier}/simulate-confirm',{}).status_code==403
with client.session_transaction(base_url='https://orcagent.fun') as s:s['wallet']='stranger'
assert get('/api/promote/mine').json['campaigns']==[]
assert post(f'/api/promote/{identifier}/pay',{}).status_code==404
print('PROMOTIONS_PRODUCTION_WSGI_PASS')
'''

class ProductionPromotions(unittest.TestCase):
    def test_installed_security_payments_recovery_and_statistics(self):
        with tempfile.TemporaryDirectory() as data:
            env={**os.environ,'DATA_DIR':data,'PYTHONPATH':str(Path(__file__).resolve().parents[1])}
            run=subprocess.run([sys.executable,'-c',PROBE],cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,text=True,timeout=90)
            self.assertEqual(run.returncode,0,run.stdout[-2500:]+run.stderr[-2500:])
            self.assertIn('PROMOTIONS_PRODUCTION_WSGI_PASS',run.stdout)
