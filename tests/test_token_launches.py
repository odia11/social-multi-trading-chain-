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
from test_token_launch import setup,icon,public_simulated_reply
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
    assert all(x['mint'] and x['trade_url']=='/live-market?mint='+x['mint'] and 'pump_url' not in x for x in result['launches'])
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
    assert post.call_count==5
    assert post.call_args.args[0]=='https://solana-rpc.publicnode.com'
    with sqlite3.connect(d.DB_FILE) as conn:
        assert conn.execute('SELECT status FROM token_launches WHERE id=?',(draft_id,)).fetchone()[0]=='submitted'
    print('PASS bounded 429 retry gives actionable error; submitted mint is never duplicated or fabricated live')
    tmp.cleanup()

def test_signed_launch_reconciles_via_readonly_fallback():
    # Simulate a real wallet signature against an actual SDK-generated mint.
    # The primary RPC remains 429, but a fixed second endpoint can verify
    # the EXACT prepared message, signatures, creator and Pump curve.
    import base64
    from solders.transaction import Transaction
    tmp,app,d=setup();client=app.test_client()
    owner=Keypair();wallet=str(owner.pubkey())
    with client.session_transaction() as sess:
        sess['wallet']=wallet;sess['csrf_token']='test-csrf'
    headers={'X-CSRF-Token':'test-csrf'}
    payload={'name':'Fallback Test','symbol':'FBACK','description':'read-only',
        'client_nonce':'rpc-fallback-test-000001','image_data':icon(),
        'reward_mode':'creator','quote_asset':'USDC'}
    draft=client.post('/api/token-launch/draft',json=payload,headers=headers).get_json()['draft']
    ident=draft['id'];blockhash=str(Keypair().pubkey())
    with patch.dict(os.environ,{'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'1'}):
        with patch('token_launch.requests.post') as api:
            api.return_value.raise_for_status=lambda:None
            api.return_value.status_code=200
            api.return_value.json=lambda:public_simulated_reply(api.call_args.kwargs['json']['method'],blockhash)
            prepared=client.post('/api/token-launch/'+ident+'/prepare',json={},headers=headers)
            assert prepared.status_code==200,prepared.get_data(as_text=True)[:200]
        partial=Transaction.from_bytes(base64.b64decode(prepared.get_json()['transaction_b64']))
        fully=Transaction.populate(partial.message,[owner.sign_message(bytes(partial.message)),partial.signatures[1]])
        assert fully.verify_with_results()==[True,True]
        sig=str(fully.signatures[0]);raw=base64.b64encode(bytes(fully)).decode()
        urls=[]
        def response():
            url=api.call_args.args[0];method=api.call_args.kwargs['json']['method']
            urls.append((url,method))
            if url==d.SOLANA_RPC:
                api.return_value.status_code=429
                return {'error':{'code':429}}
            api.return_value.status_code=200
            if method=='getTransaction':
                return {'result':{'transaction':[raw,'base64'],'meta':{'err':None}}}
            if method=='getAccountInfo':
                return {'result':{'value':{'owner':token_launch.PUMP_PROGRAM}}}
            raise AssertionError('Fallback attempted non-read-only RPC '+method)
        import token_launch
        with patch('token_launch.requests.post') as api,patch('token_launch.time.sleep'):
            api.return_value.raise_for_status=lambda:None
            # Dynamic status_code needs to update on every request before
            # rpc() inspects it; side_effect controls the response directly.
            class Reply:
                def __init__(self,code,data):self.status_code=code;self.data=data
                def raise_for_status(self):return None
                def json(self):return self.data
            def reply(url,*,json,timeout):
                urls.append((url,json['method']))
                if url==d.SOLANA_RPC:return Reply(429,{'error':{'code':429}})
                if json['method']=='getTransaction':
                    return Reply(200,{'result':{'transaction':[raw,'base64'],'meta':{'err':None}}})
                if json['method']=='getAccountInfo':
                    return Reply(200,{'result':{'value':{'owner':token_launch.PUMP_PROGRAM}}})
                raise AssertionError('Fallback used to build an unsigned transaction')
            api.side_effect=reply
            result=client.post('/api/token-launch/'+ident+'/confirm',
                    json={'stage':'create','signature':sig},headers=headers)
            assert result.status_code==200,result.get_data(as_text=True)[:250]
            assert result.get_json()['confirmed'] and result.get_json()['draft']['status']=='live'
            assert [x for x in urls if x[0]=='https://solana-rpc.publicnode.com']==[
                ('https://solana-rpc.publicnode.com','getTransaction'),
                ('https://solana-rpc.publicnode.com','getAccountInfo')]
    assert client.get('/api/token-launches').get_json()['total']==1
    print('PASS signed Pump mint moves submitted->live via verification-only fallback after primary RPC 429')
    print('PASS no wallet signature, transaction builder or funds transferred by the fallback')
    tmp.cleanup()

def test_creator_vault_is_readonly_wallet_scoped():
    from solders.pubkey import Pubkey
    import base64
    import token_launch
    tmp,app,d=setup();client=app.test_client();owner=str(Keypair().pubkey())
    other=str(Keypair().pubkey());mint=str(Keypair().pubkey());ident='c'*32
    with sqlite3.connect(d.DB_FILE) as conn:
        conn.execute('''INSERT INTO token_launches
           (id,wallet,client_nonce,name,symbol,icon_webp,reward_mode,
            quote_asset,mint,status,launch_signature,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            (ident,owner,'vault-test','Vault Test','VAULT',b'image',
             'creator','USDC',mint,'live','x'*88,int(time.time())))
    route='/api/token-launch/'+ident+'/creator-fees'
    assert client.get(route).status_code==401
    with client.session_transaction() as sess:sess['wallet']=other
    assert client.get(route).status_code==404
    with client.session_transaction() as sess:sess['wallet']=owner
    vault,_=Pubkey.find_program_address([b'creator-vault',bytes(Pubkey.from_string(owner))],
            Pubkey.from_string(token_launch.PUMP_PROGRAM))
    raw=3_962_289
    data=(bytes(Pubkey.from_string(token_launch.USDC_MINT))+
          bytes(vault)+raw.to_bytes(8,'little')+bytes(100))
    class Reply:
        def __init__(self,code,payload):self.status_code=code;self.payload=payload
        def raise_for_status(self):pass
        def json(self):return self.payload
    def provider(url,*,json,timeout):
        assert json['method']=='getAccountInfo'
        if url==d.SOLANA_RPC:return Reply(429,{'error':{'code':429}})
        return Reply(200,{'result':{'value':{'owner':token_launch.SPL_TOKEN_PROGRAM,
                'data':[base64.b64encode(data).decode(),'base64']}}})
    with patch('token_launch.requests.post',side_effect=provider),patch('token_launch.time.sleep'):
        result=client.get(route)
    assert result.status_code==200,result.get_data(as_text=True)[:200]
    assert result.get_json()['pump_vault_raw']==str(raw)
    assert result.get_json()['scope']=='creator_wallet_all_tokens_pump_bonding_curve'
    assert result.headers['Cache-Control']=='private, no-store'
    assert 'signature' not in result.get_data(as_text=True)
    with sqlite3.connect(d.DB_FILE) as conn:
        assert conn.execute('select count(*) from token_reward_claims').fetchone()[0]==0
        conn.execute("UPDATE token_launches SET status='submitted' WHERE id=?",(ident,))
    assert client.get(route).status_code==409
    print('PASS wallet-private unclaimed Pump USDC balance is wallet-wide, never treated as a payout')
    print('PASS read-only balance handles RPC fallback and never exposes unfinished launches')
    tmp.cleanup()

def test_startup_reconcile_exact_signed_creator_launch():
    import base64
    from solders.transaction import Transaction
    import token_launch
    tmp,app,d=setup();client=app.test_client();owner=Keypair();wallet=str(owner.pubkey())
    with client.session_transaction() as sess:
        sess['wallet']=wallet;sess['csrf_token']='test-csrf'
    h={'X-CSRF-Token':'test-csrf'}
    payload={'name':'Original test','symbol':'ORCAGENT','description':'test token',
        'client_nonce':'startup-reconcile-test-v1','image_data':icon(),
        'reward_mode':'creator','quote_asset':'USDC'}
    draft=client.post('/api/token-launch/draft',json=payload,headers=h).get_json()['draft']
    ident=draft['id']; blockhash=str(Keypair().pubkey())
    class Reply:
        def __init__(self,code,payload):self.status_code=code;self.payload=payload
        def raise_for_status(self):pass
        def json(self):return self.payload
    with patch.dict(os.environ,{'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'1'}):
      with patch('token_launch.requests.post') as api:
        api.return_value.status_code=200
        api.return_value.raise_for_status=lambda:None
        api.return_value.json=lambda:public_simulated_reply(api.call_args.kwargs['json']['method'],blockhash)
        prepared=client.post('/api/token-launch/'+ident+'/prepare',json={},headers=h)
        assert prepared.status_code==200,prepared.get_data(as_text=True)[:200]
    part=Transaction.from_bytes(base64.b64decode(prepared.get_json()['transaction_b64']))
    signed=Transaction.populate(part.message,[owner.sign_message(bytes(part.message)),part.signatures[1]])
    assert all(signed.verify_with_results())
    sig=str(signed.signatures[0]); b64=base64.b64encode(bytes(signed)).decode()
    with sqlite3.connect(d.DB_FILE) as conn:
        conn.execute("UPDATE token_launches SET status='submitted',launch_signature=? WHERE id=?",(sig,ident))
        # Another claimed launch with an INVALID prepared tx can never appear.
        conn.execute('''INSERT INTO token_launches
          (id,wallet,client_nonce,name,symbol,icon_webp,reward_mode,quote_asset,
           mint,status,launch_signature,prepare_tx_b64,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
           ('d'*32,wallet,'fake-launch','Fake','FAKE',b'x','creator','USDC',
            str(Keypair().pubkey()),'submitted','x'*88,'invalid base64',int(time.time())))
    requests_seen=[]
    def rpc_response(url,*,json,timeout):
        requests_seen.append((url,json['method']))
        if url==d.SOLANA_RPC:return Reply(429,{'error':{'code':429}})
        if json['method']=='getTransaction':
            return Reply(200,{'result':{'transaction':[b64,'base64'],'meta':{'err':None}}})
        if json['method']=='getAccountInfo':
            return Reply(200,{'result':{'value':{'owner':token_launch.PUMP_PROGRAM}}})
        raise AssertionError('Read-only reconciliation tried a mutating RPC')
    # No authenticated wallet session: bootstrap must work independently of
    # which wallet the user has open on an iPhone, or even if browser closed.
    with client.session_transaction() as sess:sess.clear()
    with patch('token_launch.requests.post',side_effect=rpc_response),patch('token_launch.time.sleep'):
        recovered=app._orca_reconcile_submitted_launches()
    assert recovered=={'checked':2,'recovered':1,'still_pending':1},recovered
    with sqlite3.connect(d.DB_FILE) as conn:
        assert conn.execute('SELECT status FROM token_launches WHERE id=?',(ident,)).fetchone()[0]=='live'
        assert conn.execute("SELECT status FROM token_launches WHERE id=?",('d'*32,)).fetchone()[0]=='submitted'
        assert conn.execute('SELECT COUNT(*) FROM token_reward_claims').fetchone()[0]==0
    assert client.get('/api/token-launches').get_json()['total']==1
    assert all(method in ('getTransaction','getAccountInfo') for _,method in requests_seen)
    with patch('token_launch.requests.post') as post:
        assert app._orca_reconcile_submitted_launches()['recovered']==0
        # Only forged row is retried. It has an invalid signature stored and
        # the server never fabricates success to move it live.
    print('PASS restart independently reconciles the precise saved Phantom-signed mint without logged-in wallet')
    print('PASS forged submissions remain pending and already-live token is not duplicated')
    tmp.cleanup()

def test_launch_preflight_429_fallback_is_readonly_and_idempotent():
    """Primary RPC throttling must not prevent an already-saved, capped launch."""
    import token_launch
    tmp,app,d=setup();client=app.test_client()
    owner=str(Keypair().pubkey())
    with client.session_transaction() as sess:
        sess['wallet']=owner;sess['csrf_token']='test-csrf'
    headers={'X-CSRF-Token':'test-csrf'}
    body={'name':'Throttle Test','symbol':'ORCX','description':'no broadcast',
          'client_nonce':'throttle-fallback-0001','image_data':icon(),
          'reward_mode':'creator','quote_asset':'USDC'}
    draft=client.post('/api/token-launch/draft',json=body,headers=headers).get_json()['draft']
    path='/api/token-launch/'+draft['id']+'/prepare'
    blockhash=str(Keypair().pubkey());observed=[]
    class Reply:
        def __init__(self,code,payload):
            self.status_code=code;self.payload=payload
        def raise_for_status(self):pass
        def json(self):return self.payload
    def provider(url,*,json,timeout):
        method=json['method'];observed.append((url,method))
        assert method in ('getLatestBlockhash','getBalance','getFeeForMessage','simulateTransaction')
        if url==d.SOLANA_RPC:return Reply(429,{'error':{'code':429}})
        assert url=='https://solana-rpc.publicnode.com'
        return Reply(200,public_simulated_reply(method,blockhash))
    with patch.dict(os.environ,{'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'1','ORCA_LAUNCH_RPC':''}), \
         patch('token_launch.requests.post',side_effect=provider), \
         patch('token_launch.time.sleep'):
        response=client.post(path,json={},headers=headers)
        assert response.status_code==200,response.get_data(as_text=True)[:250]
        result=response.get_json()
        assert result['mint'].endswith('orc')
        assert result['pilot_estimated_max_sol_lamports']==12_005_000
        assert result['transaction_b64']
        repeated=client.post(path,json={},headers=headers)
        assert repeated.status_code==200 and repeated.get_json()['reused']
        assert repeated.get_json()['mint']==result['mint']
    # Vanity mint grinding may take longer than the 12-second RPC cooldown.
    assert 3<=sum(url==d.SOLANA_RPC for url,_ in observed)<=6
    assert sum(url=='https://solana-rpc.publicnode.com' for url,_ in observed)>=8
    with sqlite3.connect(d.DB_FILE) as conn:
        state=conn.execute('SELECT status,mint,launch_signature FROM token_launches WHERE id=?',
                           (draft['id'],)).fetchone()
    assert state==('prepared',result['mint'],'')
    print('PASS primary 429 falls back for every read-only launch preflight method, same mint reused')
    print('PASS no signing, broadcasting, fee bypass or fabricated live launch')
    tmp.cleanup()


def test_all_launch_rpcs_429_leave_original_draft_unsent():
    import token_launch
    tmp,app,d=setup();client=app.test_client()
    owner=str(Keypair().pubkey())
    with client.session_transaction() as sess:
        sess['wallet']=owner;sess['csrf_token']='test-csrf'
    headers={'X-CSRF-Token':'test-csrf'}
    body={'name':'Offline RPC','symbol':'ORCX','client_nonce':'all-rpc-busy-0001',
          'image_data':icon(),'reward_mode':'creator','quote_asset':'USDC'}
    draft=client.post('/api/token-launch/draft',json=body,headers=headers).get_json()['draft']
    class Throttled:
        status_code=429
    seen=[]
    def overloaded(url,*,json,timeout):
        seen.append(json['method'])
        assert json['method'] in ('getBalance','getLatestBlockhash')
        return Throttled()
    with patch.dict(os.environ,{'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'1','ORCA_LAUNCH_RPC':''}), \
         patch('token_launch.requests.post',side_effect=overloaded), \
         patch('token_launch.subprocess.run') as builder, \
         patch('token_launch.time.sleep'):
        resp=client.post('/api/token-launch/'+draft['id']+'/prepare',
                         json={},headers=headers)
        assert resp.status_code==503 and 'rate-limited (429)' in resp.get_json()['msg']
        builder.assert_not_called()
    with sqlite3.connect(d.DB_FILE) as conn:
        state=conn.execute('SELECT status,mint,prepare_tx_b64,launch_signature FROM token_launches WHERE id=?',
                          (draft['id'],)).fetchone()
    assert state==('draft',None,'','')
    assert len(seen)==7
    print('PASS all RPCs 429 returns controlled error before grinding, preserves unsent draft')
    tmp.cleanup()


if __name__=='__main__':
    test_public_launch_directory()
    test_rpc_rate_limit_preserves_submitted()
    test_signed_launch_reconciles_via_readonly_fallback()
    test_creator_vault_is_readonly_wallet_scoped()
    test_startup_reconcile_exact_signed_creator_launch()
    test_launch_preflight_429_fallback_is_readonly_and_idempotent()
    test_all_launch_rpcs_429_leave_original_draft_unsent()
