"""Read-only launch dashboard and submitted-transaction verification regressions.

Uses a temporary SQLite database and mocked Solana RPC. Never signs or sends.
"""
import os
import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_token_launch import setup,icon
from solders.keypair import Keypair


def test_public_launch_directory():
    tmp,app,d=setup();client=app.test_client()
    owner=str(Keypair().pubkey());other=str(Keypair().pubkey())
    assert client.get('/launches').status_code==200
    page=client.get('/launches').get_data(as_text=True)
    assert 'Token launches' in page and '/static/token-launches.js' in page
    assert client.get('/api/token-launches').get_json()['total']==0
    assert client.get('/api/token-launches?owner=mine').status_code==401
    with sqlite3.connect(d.DB_FILE) as conn:
        # One confirmed USDC and one confirmed SOL; 22 more confirmed for
        # pagination; a submitted + a private draft must never leak.
        for n in range(26):
            status='draft' if n==23 else 'submitted' if n==24 else 'live'
            mint=str(Keypair().pubkey()) if status!='draft' else None
            wallet=owner if n==0 else other
            asset='USDC' if n%2==0 else 'SOL'
            conn.execute('''INSERT INTO token_launches
                (id,wallet,client_nonce,name,symbol,description,icon_webp,
                 reward_mode,quote_asset,mint,status,launch_signature,created_at,finalized_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (f'{n:032x}',wallet,f'nonce{n:011}',
                 'Pilot GOLD' if n==0 else 'Example'+str(n),
                 'GOLD' if n==0 else 'T'+str(n),
                 'private-unverified-description' if status!='live' else 'Public token',
                 b'image','creator',asset,mint,status,
                 ('x'*88 if status=='live' else ''),int(time.time())+n,int(time.time())+n))
        # A live flag without recorded chain signature does NOT pass.
        conn.execute("UPDATE token_launches SET launch_signature='' WHERE id=?",(f'{25:032x}',))
    response=client.get('/api/token-launches')
    assert response.headers['Cache-Control']=='private, no-store'
    result=response.get_json()
    assert result['total']==23 and len(result['launches'])==20
    assert result['counts']=={'USDC':12,'SOL':11}
    assert all(x['mint'] and x['pump_url'].endswith(x['mint']) for x in result['launches'])
    assert all(x['logo_url'].startswith('/token-launch/icon/') for x in result['launches'])
    assert all('signature' not in x and 'tx_b64' not in x for x in result['launches'])
    assert 'private-unverified-description' not in str(result)
    assert len(client.get('/api/token-launches?page=2').get_json()['launches'])==3
    assert client.get('/api/token-launches?asset=SOL').get_json()['total']==11
    assert client.get('/api/token-launches?q=Pilot%20GOLD').get_json()['total']==1
    assert client.get('/api/token-launches?q=%25').get_json()['total']==0
    assert client.get('/api/token-launches?q=%27%20OR%201%3D1').get_json()['total']==0
    assert client.get('/api/token-launches?asset=BTC').status_code==400
    assert client.get('/api/token-launches?page=0').status_code==400
    with client.session_transaction() as sess:sess['wallet']=owner
    mine=client.get('/api/token-launches?owner=mine').get_json()
    assert mine['total']==1 and mine['launches'][0]['name']=='Pilot GOLD'
    print('PASS verified-only launch dashboard, pair filters, searching, owner privacy and pagination')
    print('PASS no draft, submitted, unsigned, private reward history or private transaction data disclosed')
    tmp.cleanup()


def test_rpc_rate_limit_preserves_submitted():
    tmp,app,d=setup();client=app.test_client()
    owner=str(Keypair().pubkey());sig='x'*88;token=str(Keypair().pubkey());draft_id='a'*32
    with sqlite3.connect(d.DB_FILE) as conn:
        conn.execute('''INSERT INTO token_launches
          (id,wallet,client_nonce,name,symbol,icon_webp,reward_mode,quote_asset,
           mint,status,launch_signature,prepare_tx_b64,created_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
          (draft_id,owner,'test-nonce','Test','TEST',b'image','creator','USDC',
           token,'submitted',sig,'not-a-transaction',int(time.time())))
    with client.session_transaction() as sess:
        sess['wallet']=owner;sess['csrf_token']='test-csrf'
    with patch('token_launch.requests.post') as post,patch('token_launch.time.sleep'):
        post.return_value.status_code=429
        response=client.post('/api/token-launch/'+draft_id+'/confirm',json={'stage':'create','signature':sig},headers={'X-CSRF-Token':'test-csrf'})
    assert response.status_code==503 and 'rate-limited (429)' in response.get_json()['msg']
    assert post.call_count==3
    with sqlite3.connect(d.DB_FILE) as conn:
        assert conn.execute('SELECT status FROM token_launches WHERE id=?',(draft_id,)).fetchone()[0]=='submitted'
    print('PASS bounded 429 retry gives actionable error; submitted mint is never duplicated or fabricated live')
    tmp.cleanup()

if __name__=='__main__':
    test_public_launch_directory()
    test_rpc_rate_limit_preserves_submitted()
