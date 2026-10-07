"""Read-only safety regression: insufficient SOL must fail before mint grinding.

This targets the actual 0.0043 SOL mainnet failure observed in a dry run,
without using the affected user's wallet, private data, or any funds.
"""
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch
from solders.keypair import Keypair
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_token_launch import setup,icon

def test_low_sol_is_actionable_and_preserves_draft():
    tmp,app,d=setup()
    user=str(Keypair().pubkey());c=app.test_client()
    with c.session_transaction() as s:s['wallet']=user;s['csrf_token']='test-csrf'
    h={'X-CSRF-Token':'test-csrf'}
    body={'name':'Low SOL test','symbol':'LSOL','image_data':icon(),
          'client_nonce':'low-sol-readonly-001','quote_asset':'SOL',
          'reward_mode':'creator'}
    draft=c.post('/api/token-launch/draft',json=body,headers=h).get_json()['draft']
    path='/api/token-launch/'+draft['id']+'/prepare'
    seen=[]
    class Reply:
        status_code=200
        def raise_for_status(self):pass
        def json(self):return {'result':{'value':4_300_000}}
    def low_rpc(url,*,json,timeout):
        seen.append(json['method'])
        assert json['method']=='getBalance', 'Mint generation must not occur with insufficient SOL'
        return Reply()
    with patch.dict(os.environ,{'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'1'}), \
         patch('token_launch.requests.post',side_effect=low_rpc), \
         patch('token_launch.subprocess.run') as builder:
        first=c.post(path,json={},headers=h)
        assert first.status_code==409, first.get_data(as_text=True)
        msg=first.get_json()['msg']
        assert 'Insufficient SOL' in msg and '0.004300 SOL' in msg
        # Launches are funded with native SOL (#155): it says to add SOL, and how much.
        assert 'Add SOL to your connected wallet' in msg and '0.01 SOL' in msg
        assert 'No token was created' in msg
        assert 'transaction_b64' not in first.get_json()
        assert c.post(path,json={},headers=h).status_code==409
        builder.assert_not_called()
    assert seen==['getBalance','getBalance']
    with sqlite3.connect(d.DB_FILE) as conn:
        assert conn.execute('SELECT status,mint,launch_signature FROM token_launches WHERE id=?',
            (draft['id'],)).fetchone()==('draft',None,'')
    print('PASS 0.0043 SOL user receives clear funding requirement; same saved draft, no mint/grind/send')
    tmp.cleanup()

if __name__=='__main__':
    test_low_sol_is_actionable_and_preserves_draft()
