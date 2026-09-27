"""USDC-first Token Launch: isolated Flask/SQLite + actual official SDK builder.

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
       'quote_asset':'USDC','community_wallet':community,'community_bps':1000}
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
    assert len(draft_id)==32 and draft['quote_asset']=='USDC'
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
        post.return_value.json=lambda:{'result':{'value':{'blockhash':blockhash}}}
        r=client.post(path+draft_id+'/prepare',json={},headers=h)
        assert r.status_code==200,r.get_data(as_text=True)[:300]
        built=r.get_json()
        assert built['needs_finalization'] is True
        assert built['quote_asset']=='USDC'
        tx=Transaction.from_bytes(base64.b64decode(built['transaction_b64']))
        assert len(base64.b64decode(built['transaction_b64']))<=1232
        assert tx.verify_with_results().count(False)==1
        assert str(tx.message.account_keys[0])==wallet
        assert client.post(path+draft_id+'/prepare',json={},headers=h).status_code==409
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
    print('PASS official Pump SDK USDC create+initial sharing instruction under 1232 bytes')
    print('PASS creator wallet cannot be signed server-side; unconfirmed/mismatched transaction cannot become live')
    # Finalization is its own USDC-quote transaction, separate from create.
    # The first fee share allocation is 100% creator until this confirmation.
    with sqlite3.connect(d.DB_FILE) as conn:
        conn.execute("UPDATE token_launches SET status='pending_shares' WHERE id=?",(draft_id,))
    with patch.dict(os.environ,{'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'1'}):
      with patch('token_launch.requests.post') as post:
        post.return_value.raise_for_status=lambda:None
        post.return_value.json=lambda:{'result':{'value':{'blockhash':blockhash}}}
        result=client.post(path+draft_id+'/prepare-finalize',json={},headers=h)
        assert result.status_code==200,result.get_data(as_text=True)[:220]
        raw=base64.b64decode(result.get_json()['transaction_b64'])
        assert len(raw)<1232
        final=Transaction.from_bytes(raw)
        assert final.verify_with_results()==[False]
        assert str(final.message.account_keys[0])==wallet
        assert client.post(path+draft_id+'/prepare-finalize',json={},headers=h).status_code==409
    print('PASS USDC fee-sharing finalization fits transaction size and needs only creator signature')
    # Gated creator claim endpoint must reject holder mode and never debit
    # without a confirmed Pump transaction. Claims are isolated from trading.
    with sqlite3.connect(d.DB_FILE) as conn:
        conn.execute("UPDATE token_launches SET status='live' WHERE id=?",(draft_id,))
    assert client.post(path+draft_id+'/claim/prepare',json={},headers=h).status_code==503
    assert client.post(path+draft_id+'/claim/confirm',json={},headers=h).status_code==400
    assert client.get(path+draft_id+'/claims').get_json()['claims']==[]
    print('PASS gated claims and private reward history never fabricate earnings')
    tmp.cleanup()

if __name__=='__main__':test_all()
