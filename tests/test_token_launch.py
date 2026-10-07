"""SOL-paired Token Launch (#155): isolated Flask/SQLite + actual official SDK builder.

Never contacts mainnet or signs with a real wallet. Transaction payloads are
partially signed only by an ephemeral mint key, never the creator wallet.
"""
import base64
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from flask import Flask,session,render_template
from markupsafe import Markup
from PIL import Image
from solders.keypair import Keypair
from solders.transaction import Transaction
import token_launch

class Fake:
    pass

def setup():
    tmp=tempfile.TemporaryDirectory(prefix='orca-pump-launch-test-')
    app=Flask('tokenlaunch',template_folder=str(ROOT/'templates'))
    app.secret_key='token-launch-tests-only'
    d=Fake()
    d.app=app;d.DB_FILE=str(Path(tmp.name)/'launches.db');d.BASE=str(ROOT)
    d.SOLANA_RPC_URL='';d.SOLANA_RPC='https://rpc.test.invalid'
    d.is_valid_solana_address=lambda x:bool(token_launch._B58.fullmatch(x or ''))
    d.rate_limit=lambda *args,**kwargs:lambda fn:fn
    d._authenticated_wallet=lambda:'' if session.get('readonly') else session.get('wallet','')
    d._get_csrf_token=lambda:session.setdefault('csrf_token','test-csrf')
    d._validate_csrf=lambda tok:tok=='test-csrf' and session.get('csrf_token')=='test-csrf'
    d._render_no_cache=render_template
    d._navbar_html=lambda _:Markup('<nav>OrcAgent</nav>')
    token_launch.install(d)
    return tmp,app,d

def public_simulated_reply(method,blockhash):
    """Read-only mocked RPC for capped PUBLIC launch preparations, no broadcast."""
    if method=='getLatestBlockhash':
        return {'result':{'value':{'blockhash':blockhash}}}
    if method=='getBalance':
        return {'result':{'value':100_000_000}}
    if method=='getFeeForMessage':
        return {'result':{'value':5000}}
    if method=='simulateTransaction':
        return {'result':{'value':{'err':None,'accounts':[{'lamports':88_000_000}]}}}
    return None

def icon():
    img=Image.new('RGB',(40,40),(10,20,30));out=io.BytesIO()
    img.save(out,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()

def test_all():
    tmp,app,d=setup();wallet=str(Keypair().pubkey());community=str(Keypair().pubkey())
    client=app.test_client()
    path='/api/token-launch/'
    payload={'client_nonce':'test-client-nonce-00001','name':'Example Token','symbol':'exmp',
       'description':'Example description','image_data':icon(),'reward_mode':'community',
       'quote_asset':'SOL','community_wallet':community,'community_bps':1000}
    os.environ.pop('ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED',None)
    assert client.get('/token-launch').status_code==302
    assert client.post(path+'draft',json=payload).status_code==401
    with client.session_transaction() as s:s['wallet']=wallet;s['csrf_token']='test-csrf'
    assert client.get('/token-launch').status_code==200
    html=client.get('/token-launch').get_data(as_text=True)
    assert 'Creator + Community Rewards' in html and 'Preflight mode' in html
    assert client.post(path+'draft',json=payload).status_code==403
    assert client.post(path+'draft',json={**payload,'reward_mode':'holder','community_wallet':'x'},headers={'X-CSRF-Token':'wrong'}).status_code==403
    h={'X-CSRF-Token':'test-csrf'}
    assert client.post(path+'draft',json={**payload,'quote_asset':'BTC'},headers=h).status_code==400
    assert client.post(path+'draft',json={**payload,'quote_asset':[]},headers=h).status_code==400
    assert client.post(path+'draft',json={**payload,'reward_mode':{}},headers=h).status_code==400
    assert client.post(path+'draft',json={**payload,'community_wallet':wallet},headers=h).status_code==400
    assert client.post(path+'draft',json={**payload,'community_bps':10000},headers=h).status_code==400
    assert client.post(path+'draft',json={**payload,'image_data':'data:image/svg+xml;base64,AAAA'},headers=h).status_code==400
    r=client.post(path+'draft',json=payload,headers=h)
    assert r.status_code==201,r.get_data(as_text=True)
    draft=r.get_json()['draft'];draft_id=draft['id']
    assert len(draft_id)==32 and draft['quote_asset']=='SOL'
    assert draft['symbol']=='EXMP' and draft['community_bps']==1000
    repeated=client.post(path+'draft',json=payload,headers=h)
    assert repeated.status_code==200 and repeated.get_json()['draft']['id']==draft_id
    assert len(client.get(path+'mine').get_json()['launches'])==1
    # Nobody else can edit, prepare, view claims or delete this user's draft.
    assert client.get(path+draft_id+'/claims').status_code==200
    assert client.get(path+draft_id+'/claims').get_json()['claims']==[]
    assert client.post(path+draft_id+'/claim/prepare',json={},headers=h).status_code==503
    m=client.get('/token-launch/metadata/'+draft_id)
    assert m.status_code==200 and m.get_json()['symbol']=='EXMP'
    assert m.get_json()['image'].endswith(draft_id)
    img=client.get('/token-launch/icon/'+draft_id)
    assert img.status_code==200 and img.headers['Content-Type']=='image/webp'
    with client.session_transaction() as s:s['wallet']=str(Keypair().pubkey())
    assert client.get(path+'mine').get_json()['launches']==[]
    assert client.post(path+draft_id+'/prepare',json={},headers=h).status_code==503
    assert client.post(path+draft_id+'/delete-draft',json={},headers=h).status_code==409
    assert client.get(path+draft_id+'/claims').status_code==404
    with client.session_transaction() as s:s['wallet']=wallet
    assert client.post(path+draft_id+'/prepare',json={},headers=h).status_code==503
    print('PASS private per-wallet drafts, idempotency, CSRF and public durable metadata/icon')
    print('PASS reward mode and share validation; no mainnet transaction while feature gated')
    with sqlite3.connect(d.DB_FILE) as conn:
        assert len(conn.execute('SELECT * FROM token_launches').fetchall())==1
        assert not any('private_key' in x[1] for x in conn.execute('PRAGMA table_info(token_launches)').fetchall())
    blockhash=str(Keypair().pubkey())
    with patch.dict(os.environ,{'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'1'}):
      with patch('token_launch.requests.post') as post:
        post.return_value.raise_for_status=lambda:None
        post.return_value.json=lambda:public_simulated_reply(post.call_args.kwargs['json']['method'],blockhash)
        r=client.post(path+draft_id+'/prepare',json={},headers=h)
        assert r.status_code==200,r.get_data(as_text=True)[:300]
        built=r.get_json()
        assert built['mint'].endswith('orc')
        assert 'mint_secret' not in built
        assert built['needs_finalization'] is True
        assert built['quote_asset']=='SOL'
        tx=Transaction.from_bytes(base64.b64decode(built['transaction_b64']))
        assert len(base64.b64decode(built['transaction_b64']))<=1232
        assert tx.verify_with_results().count(False)==1
        assert str(tx.message.account_keys[0])==wallet
        reused=client.post(path+draft_id+'/prepare',json={},headers=h)
        assert reused.status_code==200 and reused.get_json()['reused'] is True
        assert reused.get_json()['transaction_b64']==built['transaction_b64']
        assert client.post(path+draft_id+'/delete-draft',json={},headers=h).status_code==409
        # A made-up signature cannot complete launch. An unconfirmed signature
        # can only enter submitted state, never live.
        assert client.post(path+draft_id+'/confirm',json={'stage':'create','signature':'x'},headers=h).status_code==400
        post.return_value.json=lambda:{'result':None}
        fake='1'*88
        sig=client.post(path+draft_id+'/confirm',json={'stage':'create','signature':fake},headers=h)
        assert sig.status_code==202,sig.get_data(as_text=True)[:200]
        assert sig.get_json()['confirmed'] is False
        assert sig.get_json()['draft']['status']=='submitted'
        assert client.post(path+draft_id+'/prepare-finalize',json={},headers=h).status_code==409
    print('PASS official Pump SDK SOL create+initial sharing instruction under 1232 bytes')
    print('PASS creator wallet cannot be signed server-side; unconfirmed/mismatched transaction cannot become live')
    # Finalization is its own SOL-quote transaction, separate from create.
    # The first fee share allocation is 100% creator until this confirmation.
    with sqlite3.connect(d.DB_FILE) as conn:
        conn.execute("UPDATE token_launches SET status='pending_shares' WHERE id=?",(draft_id,))
    with patch.dict(os.environ,{'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'1'}):
      with patch('token_launch.requests.post') as post:
        post.return_value.raise_for_status=lambda:None
        after={'lamports':40_000_000}
        def final_rpc():
            method=post.call_args.kwargs['json']['method']
            if method=='simulateTransaction':
                return {'result':{'value':{'err':None,'accounts':[{'lamports':after['lamports']}]}}}
            return public_simulated_reply(method,blockhash)
        post.return_value.json=final_rpc
        too_expensive=client.post(path+draft_id+'/prepare-finalize',json={},headers=h)
        assert too_expensive.status_code==503 and 'SOL budget' in too_expensive.get_json()['msg']
        assert 'transaction_b64' not in too_expensive.get_json()
        after['lamports']=88_000_000
        result=client.post(path+draft_id+'/prepare-finalize',json={},headers=h)
        assert result.status_code==200,result.get_data(as_text=True)[:220]
        assert result.get_json()['pilot_estimated_max_sol_lamports']==12_005_000
        raw=base64.b64decode(result.get_json()['transaction_b64'])
        assert len(raw)<1232
        final=Transaction.from_bytes(raw)
        assert final.verify_with_results()==[False]
        assert str(final.message.account_keys[0])==wallet
        second=client.post(path+draft_id+'/prepare-finalize',json={},headers=h)
        assert second.status_code==200 and second.get_json()['reused'] is True
        assert second.get_json()['transaction_b64']==result.get_json()['transaction_b64']
    print('PASS retry after Phantom rejection reuses identical signed mint and share transactions')
    print('PASS SOL fee-sharing finalization fits transaction size and needs only creator signature')
    print('PASS public fee-sharing approval refuses simulated charges above 0.05 SOL')
    # Gated creator claim endpoint must reject holder mode and never debit
    # without a confirmed Pump transaction. Claims are isolated from trading.
    with sqlite3.connect(d.DB_FILE) as conn:
        conn.execute("UPDATE token_launches SET status='live' WHERE id=?",(draft_id,))
    assert client.post(path+draft_id+'/claim/prepare',json={},headers=h).status_code==503
    assert client.post(path+draft_id+'/claim/confirm',json={},headers=h).status_code==400
    assert client.get(path+draft_id+'/claims').get_json()['claims']==[]
    print('PASS gated claims and private reward history never fabricate earnings')
    tmp.cleanup()

def test_allowlisted_mainnet_pilot():
    # Never open real-value signing to all users while preflighting one wallet.
    tmp,app,d=setup()
    client=app.test_client()
    owner=str(Keypair().pubkey());outsider=str(Keypair().pubkey())
    with client.session_transaction() as sess:
        sess['wallet']=owner;sess['csrf_token']='test-csrf'
    flags={'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'0',
      'ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_ENABLED':'0',
      'ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_WALLETS':owner}
    with patch.dict(os.environ,flags):
      assert client.get('/api/token-launch/config').get_json()['enabled'] is False
      assert 'Preflight mode' in client.get('/token-launch').get_data(as_text=True)
    flags['ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_ENABLED']='1'
    with patch.dict(os.environ,flags):
      assert client.get('/api/token-launch/config').get_json()['enabled'] is True
      assert 'Preflight mode' not in client.get('/token-launch').get_data(as_text=True)
      with client.session_transaction() as sess:sess['wallet']=outsider
      assert client.get('/api/token-launch/config').get_json()['enabled'] is False
      assert 'Preflight mode' in client.get('/token-launch').get_data(as_text=True)
      # Invalid, empty and a lookalike wallet do not bypass equality.
      flags['ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_WALLETS']='not_a_wallet'
      with patch.dict(os.environ,flags):
        assert client.get('/api/token-launch/config').get_json()['enabled'] is False
      flags['ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_WALLETS']=owner+','+outsider
      with patch.dict(os.environ,flags):
        assert client.get('/api/token-launch/config').get_json()['enabled'] is True
    print('PASS mainnet pilot requires BOTH switch and exact authenticated wallet allowlist')
    print('PASS unapproved users remain in draft-only mode, including when another wallet is approved')
    tmp.cleanup()

def test_creator_pilot_wallet_budget():
    tmp,app,d=setup();client=app.test_client()
    wallet=str(Keypair().pubkey());other=str(Keypair().pubkey())
    with client.session_transaction() as sess:
        sess['wallet']=wallet;sess['csrf_token']='test-csrf'
    headers={'X-CSRF-Token':'test-csrf'}
    base={'name':'OrcAgent Pilot Test','symbol':'ORCAP','image_data':icon(),
          'quote_asset':'SOL','reward_mode':'creator',
          'client_nonce':'creator-pilot-100pc-0001'}
    flags={'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'0',
           'ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_ENABLED':'1',
           'ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_WALLETS':wallet}
    state={'before':50_000_000,'after':26_000_000,'fee':5000,'err':None}
    with patch.dict(os.environ,flags):
      conf=client.get('/api/token-launch/config').get_json()
      assert conf['pilot_creator_only'] and conf['default_reward_mode']=='creator'
      assert conf['pilot_max_sol_lamports']==30_000_000
      assert conf['pilot_max_launch_sol_lamports']==25_000_000
      assert conf['pilot_max_trade_usdc_micro']==2_000_000
      html=client.get('/token-launch').get_data(as_text=True)
      assert '100% Creator Rewards' in html
      assert 'value="community" disabled' in html
      assert 'value="creator" checked' in html
      assert 'value="holder"' not in html
      # Launches are paired with native SOL since #155; USDC is no longer offered.
      assert 'name="tl-asset" value="SOL" checked' in html
      assert 'name="tl-asset" value="USDC"' not in html
      assert client.post('/api/token-launch/draft',json={**base,
          'reward_mode':'community','community_wallet':other,
          'community_bps':1000},headers=headers).status_code==400
      assert client.post('/api/token-launch/draft',json={**base,
          'quote_asset':'USDC'},headers=headers).status_code==400
      first=client.post('/api/token-launch/draft',json=base,headers=headers)
      assert first.status_code==201,first.get_data(as_text=True)[:150]
      draft_id=first.get_json()['draft']['id']
      path='/api/token-launch/'+draft_id+'/prepare'
      blockhash=str(Keypair().pubkey())
      with patch('token_launch.requests.post') as rpc:
        rpc.return_value.raise_for_status=lambda:None
        def answer():
            method=rpc.call_args.kwargs['json']['method']
            if method=='getLatestBlockhash':
                return {'result':{'value':{'blockhash':blockhash}}}
            if method=='getBalance':
                return {'result':{'value':state['before']}}
            if method=='getFeeForMessage':
                return {'result':{'value':state['fee']}}
            if method=='simulateTransaction':
                return {'result':{'value':{'err':state['err'],
                    'logs':state.get('logs'),
                    'accounts':[{'lamports':state['after']}]}}}
            raise AssertionError('Unexpected RPC method '+method)
        rpc.return_value.json=answer
        blocked=client.post(path,json={},headers=headers)
        assert blocked.status_code==200,blocked.get_data(as_text=True)[:160]
        assert blocked.get_json()['pilot_estimated_max_sol_lamports']==24_005_000
        reused=client.post(path,json={},headers=headers)
        assert reused.status_code==200 and reused.get_json()['reused'] is True
        state['after']=10_000_000
        over=client.post(path,json={},headers=headers)
        assert over.status_code==503 and 'SOL budget' in over.get_json()['msg']
        state['after']=26_000_000
        state['err']={'InstructionError':[0,'Custom']}
        failed=client.post(path,json={},headers=headers)
        assert failed.status_code==503 and 'simulation failed' in failed.get_json()['msg']
        state['before']=890_880
        state['err']={'InstructionError':[0,{'Custom':1}]}
        state['logs']=['Transfer: insufficient lamports 880880, need 1838960']
        low=client.post(path,json={},headers=headers)
        assert low.status_code==503 and 'Insufficient SOL' in low.get_json()['msg']
        assert '0.000890880 SOL' in low.get_json()['msg']
        assert 'Full transaction cost is not yet known' in low.get_json()['msg']
        assert 'transaction_b64' not in low.get_json()
        state['logs']=['Program log: Transfer: insufficient lamports 880880, need 1838960']
        prefixed=client.post(path,json={},headers=headers)
        assert prefixed.status_code==503 and 'Insufficient SOL' in prefixed.get_json()['msg']
        assert 'Add SOL to your connected wallet' in prefixed.get_json()['msg']
        state['logs']=None
        generic=client.post(path,json={},headers=headers)
        assert generic.status_code==503 and 'simulation failed' in generic.get_json()['msg']
        state['err']='InsufficientFundsForFee'
        fee_low=client.post(path,json={},headers=headers)
        assert fee_low.status_code==503 and 'Insufficient SOL' in fee_low.get_json()['msg']
        assert 'transaction_b64' not in fee_low.get_json()
        state['before']=50_000_000
        state['err']=None
        next_draft=client.post('/api/token-launch/draft',json={**base,
            'client_nonce':'creator-pilot-100pc-0002'},headers=headers)
        assert next_draft.status_code==201
        second=client.post('/api/token-launch/'+next_draft.get_json()['draft']['id']+'/prepare',
               json={},headers=headers)
        assert second.status_code==409 and 'one test token' in second.get_json()['msg']
    print('PASS creator-only SOL pilot has 0.03 SOL cost gate')
    print('PASS simulated network failure, excess SOL charges and second mint fail closed')
    print('PASS insufficient SOL/rent/fee failures are actionable; unknown errors stay generic; no transaction returned')
    tmp.cleanup()

def test_exact_onchain_transaction_verification():
    """Simulated RPC response uses cryptographically signed bytes, not a stubbed verdict."""
    from solders.transaction import Transaction as Tx
    tmp,app,d=setup()
    client=app.test_client();owner=Keypair();wallet=str(owner.pubkey())
    with client.session_transaction() as sess:
        sess['wallet']=wallet;sess['csrf_token']='test-csrf'
    headers={'X-CSRF-Token':'test-csrf'}
    draft=client.post('/api/token-launch/draft',json={
        'client_nonce':'exact-signature-test-0001','name':'Exact Test',
        'symbol':'EXACT','image_data':icon(),'reward_mode':'creator',
        'quote_asset':'SOL'},headers=headers).get_json()['draft']
    draft_id=draft['id'];path='/api/token-launch/'+draft_id
    blockhash=str(Keypair().pubkey())
    state={'result':None,'curve_exists':True}
    with patch.dict(os.environ,{'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'1'}):
      with patch('token_launch.requests.post') as rpc:
        rpc.return_value.raise_for_status=lambda:None
        def reply():
            method=rpc.call_args.kwargs['json']['method']
            simulated=public_simulated_reply(method,blockhash)
            if simulated is not None:return simulated
            if method=='getTransaction':return {'result':state['result']}
            if method=='getAccountInfo':
                return {'result':{'value':{'owner':token_launch.PUMP_PROGRAM}
                        if state['curve_exists'] else None}}
            raise AssertionError('Unexpected RPC method '+method)
        rpc.return_value.json=reply
        prepared=client.post(path+'/prepare',json={},headers=headers)
        assert prepared.status_code==200,prepared.get_data(as_text=True)[:160]
        part=Tx.from_bytes(base64.b64decode(prepared.get_json()['transaction_b64']))
        signed=Tx.populate(part.message,[owner.sign_message(bytes(part.message)),part.signatures[1]])
        assert signed.verify_with_results()==[True,True]
        sig=str(signed.signatures[0]);raw=base64.b64encode(bytes(signed)).decode()
        state['result']={'transaction':[raw,'base64'],'meta':{'err':None}}
        incorrect=client.post(path+'/confirm',json={'stage':'create','signature':str(Keypair().sign_message(b'unrelated'))},headers=headers)
        assert incorrect.status_code==400,incorrect.get_data(as_text=True)[:180]
        state['curve_exists']=False
        not_verified=client.post(path+'/confirm',json={'stage':'create','signature':sig},headers=headers)
        assert not_verified.status_code==503
        state['curve_exists']=True
        verified=client.post(path+'/confirm',json={'stage':'create','signature':sig},headers=headers)
        assert verified.status_code==200,verified.get_data(as_text=True)[:180]
        assert verified.get_json()['confirmed'] is True
        assert verified.get_json()['draft']['status']=='live'
        again=client.post(path+'/confirm',json={'stage':'create','signature':sig},headers=headers)
        assert again.status_code==200 and again.get_json()['confirmed'] is True
    print('PASS exact Pump message and both Ed25519 signatures verified against signed RPC bytes')
    print('PASS forged signatures and absent on-chain mint cannot mark a launch as live')
    tmp.cleanup()

def test_prepared_recovery():
    # A Phantom cancel must allow re-approval, not strand a noncustodial mint.
    # Once the actual blockhash is invalid, a *different* mint may only be
    # built after a read-only proof the original Pump curve does not exist.
    tmp,app,d=setup()
    client=app.test_client()
    wallet=str(Keypair().pubkey())
    community=str(Keypair().pubkey())
    blockhash=str(Keypair().pubkey())
    with client.session_transaction() as sess:
        sess['wallet']=wallet;sess['csrf_token']='test-csrf'
    headers={'X-CSRF-Token':'test-csrf'}
    draft=client.post('/api/token-launch/draft',json={
        'client_nonce':'recovery-test-nonce-0001','name':'Recovery Test',
        'symbol':'RECOV','image_data':icon(),'reward_mode':'community',
        'quote_asset':'SOL','community_wallet':community,'community_bps':1000
    },headers=headers).get_json()['draft']
    path='/api/token-launch/'+draft['id']+'/prepare'
    state={'blockhash_valid':True,'curve_exists':False}
    with patch.dict(os.environ,{'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'1'}):
      with patch('token_launch.requests.post') as rpc:
        rpc.return_value.raise_for_status=lambda:None
        def reply():
            method=rpc.call_args.kwargs['json']['method']
            simulated=public_simulated_reply(method,blockhash)
            if simulated is not None:return simulated
            if method=='isBlockhashValid':
                return {'result':{'value':state['blockhash_valid']}}
            if method=='getAccountInfo':
                return {'result':{'value':{'owner':token_launch.PUMP_PROGRAM}
                        if state['curve_exists'] else None}}
            raise AssertionError('Unexpected Solana RPC method '+method)
        rpc.return_value.json=reply
        first=client.post(path,json={},headers=headers)
        assert first.status_code==200,first.get_data(as_text=True)[:200]
        mint=first.get_json()['mint'];raw=first.get_json()['transaction_b64']
        second=client.post(path,json={},headers=headers)
        assert second.status_code==200 and second.get_json()['transaction_b64']==raw
        with sqlite3.connect(d.DB_FILE) as conn:
            conn.execute('UPDATE token_launches SET prepared_at=prepared_at-500 WHERE id=?',(draft['id'],))
        still_valid=client.post(path,json={},headers=headers)
        assert still_valid.status_code==200 and still_valid.get_json()['mint']==mint
        state['blockhash_valid']=False;state['curve_exists']=True
        already_created=client.post(path,json={},headers=headers)
        assert already_created.status_code==409
        assert 'already exists' in already_created.get_json()['msg']
        state['curve_exists']=False
        regenerated=client.post(path,json={},headers=headers)
        assert regenerated.status_code==200,regenerated.get_data(as_text=True)[:220]
        assert regenerated.get_json()['mint']!=mint
        assert regenerated.get_json()['transaction_b64']!=raw
        with sqlite3.connect(d.DB_FILE) as conn:
            status=conn.execute('SELECT status FROM token_launches WHERE id=?',(draft['id'],)).fetchone()[0]
        assert status=='prepared'
    print('PASS Phantom cancel retries the same partially signed transaction')
    print('PASS expired blockhash + verified missing Pump curve permit safe mint regeneration')
    print('PASS an existing on-chain token cannot be regenerated as a duplicate')
    tmp.cleanup()

def test_public_creators_share_safe_launch_path():
    """Two unrelated logged-in users can prepare, but never without cost preflight."""
    tmp,app,d=setup();client=app.test_client()
    owners=[str(Keypair().pubkey()),str(Keypair().pubkey())]
    flags={'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'1',
           'ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_ENABLED':'0',
           'ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_WALLETS':''}
    header={'X-CSRF-Token':'test-csrf'}
    blockhash=str(Keypair().pubkey())
    state={'before':100_000_000,'after':40_000_000}
    with patch.dict(os.environ,flags):
      for index,wallet in enumerate(owners):
        with client.session_transaction() as sess:
            sess['wallet']=wallet;sess['csrf_token']='test-csrf'
        conf=client.get('/api/token-launch/config').get_json()
        assert conf['enabled'] and not conf['pilot_creator_only']
        assert conf['capabilities']=={'creator':True,'community':True,'holder':False}
        assert 'Preflight mode' not in client.get('/token-launch').get_data(as_text=True)
        body={'client_nonce':f'public-creator-{index}-nonce-0001',
             'name':'Public Creator','symbol':f'PUB{index}',
             'reward_mode':'creator','quote_asset':'SOL','image_data':icon()}
        created=client.post('/api/token-launch/draft',json=body,headers=header)
        assert created.status_code==201,created.get_data(as_text=True)[:160]
        ident=created.get_json()['draft']['id']
        with patch('token_launch.requests.post') as rpc:
          rpc.return_value.status_code=200
          rpc.return_value.raise_for_status=lambda:None
          def respond():
            method=rpc.call_args.kwargs['json']['method']
            if method=='getBalance':return {'result':{'value':state['before']}}
            if method=='simulateTransaction':return {'result':{'value':{
                'err':None,'accounts':[{'lamports':state['after']}]}}}
            return public_simulated_reply(method,blockhash)
          rpc.return_value.json=respond
          endpoint='/api/token-launch/'+ident+'/prepare'
          if index==0:
            refused=client.post(endpoint,json={},headers=header)
            assert refused.status_code==503 and 'SOL budget' in refused.get_json()['msg']
            assert 'transaction_b64' not in refused.get_json()
            with sqlite3.connect(d.DB_FILE) as conn:
              assert conn.execute('SELECT status FROM token_launches WHERE id=?',(ident,)).fetchone()[0]=='draft'
            state['after']=88_000_000
          prepared=client.post(endpoint,json={},headers=header)
          assert prepared.status_code==200,prepared.get_data(as_text=True)[:180]
          data=prepared.get_json()
          assert data['mint'].endswith('orc')
          assert data['pilot_estimated_max_sol_lamports']==12_005_000
          assert 'mint_secret' not in data
          assert str(Transaction.from_bytes(base64.b64decode(data['transaction_b64'])).message.account_keys[0])==wallet
    print('PASS two independent authenticated public creators can prepare own ORC mints')
    print('PASS public launch cost >0.05 SOL fails closed before wallet approval')
    print('PASS successful capped public launch returns owner-bound partially signed transaction only')
    tmp.cleanup()

if __name__=='__main__':
    test_all()
    test_allowlisted_mainnet_pilot()
    test_creator_pilot_wallet_budget()
    test_exact_onchain_transaction_verification()
    test_prepared_recovery()
    test_public_creators_share_safe_launch_path()
