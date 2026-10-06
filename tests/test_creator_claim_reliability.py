"""Creator-fee claim reliability: terminal failures, auto-settlement and concurrency.

All Solana/RPC/builder work is mocked. No real transaction is signed for or
sent to mainnet; local test keypairs only authenticate prepared test messages.
"""
import base64
import json
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

from solders.hash import Hash
from solders.transaction import Transaction

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tests'))

import token_launch  # noqa: E402
from test_creator_rewards_preflight import fixture, Reply  # noqa: E402


def signed_fixture():
    tmp,app,d,client,owner,ident,raw,built=fixture()
    tx=Transaction.from_bytes(base64.b64decode(raw))
    signed=Transaction.populate(tx.message,[owner.sign_message(bytes(tx.message))])
    assert all(signed.verify_with_results())
    return tmp,app,d,client,owner,ident,raw,built,signed


def rpc_for_preparation(json_body):
    method=json_body['method']
    if method=='getLatestBlockhash':
        return Reply({'value':{'blockhash':str(Hash.default())}})
    if method=='getBalance':
        return Reply({'value':100_000_000})
    if method=='getFeeForMessage':
        return Reply({'value':5_000})
    if method=='simulateTransaction':
        return Reply({'value':{'err':None,'accounts':[{'lamports':98_000_000}]}})
    if method=='getSignaturesForAddress':
        return Reply([])
    if method=='isBlockhashValid':
        return Reply({'value':True})
    raise AssertionError('Unexpected read-only RPC '+method)


def test_exact_failed_claim_is_terminal_and_retryable():
    tmp,app,d,client,owner,ident,raw,built,signed=signed_fixture()
    claim_id='a'*32;wallet=str(owner.pubkey());sig=str(signed.signatures[0])
    with sqlite3.connect(d.DB_FILE) as c:
        c.execute('''INSERT INTO token_reward_claims
          (id,launch_id,wallet,mint,quote_asset,reward_mode,accrued_raw,
           accrued_scope,transaction_b64,created_at)
          VALUES (?,?,?,?,?,?,?,?,?,?)''',
          (claim_id,ident,wallet,built['mint'],'USDC','creator','3962289',
           'creator_wallet_all_tokens',raw,int(time.time())))
    signed_b64=base64.b64encode(bytes(signed)).decode()
    def failed_rpc(url,*,json,timeout):
        assert json['method']=='getTransaction'
        return Reply({'transaction':[signed_b64,'base64'],
                      'meta':{'err':{'InstructionError':[0,'Custom']}}})
    body={'claim_id':claim_id,'signature':sig}
    with patch('token_launch.requests.post',side_effect=failed_rpc):
        response=client.post('/api/token-launch/'+ident+'/claim/confirm',json=body,
            headers={'X-CSRF-Token':'test-csrf'})
    assert response.status_code==200,response.get_data(as_text=True)
    data=response.get_json()
    assert data['status']=='failed' and data['confirmed'] is False
    with sqlite3.connect(d.DB_FILE) as c:
        assert c.execute('SELECT status,signature FROM token_reward_claims WHERE id=?',
            (claim_id,)).fetchone()==('failed',sig)
    earnings=client.get('/api/token-launch/creator-earnings').get_json()
    assert earnings['failed_claims']==1 and earnings['pending_claims']==0

    # A terminal failed exact transaction must not strand the creator. A new
    # prepared claim is allowed, but still only after the usual read-only
    # builder + simulation gates.
    def rpc(url,*,json,timeout):
        return rpc_for_preparation(json)
    def builder(args,**kwargs):
        assert args[-1].endswith('build-reward-claim.cjs')
        return SimpleNamespace(returncode=0,stdout=json_module.dumps(built),stderr='')
    json_module=json
    with patch.dict(os.environ,{'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'1'}),\
         patch('token_launch.requests.post',side_effect=rpc),\
         patch('token_launch.subprocess.run',side_effect=builder):
        retry=client.post('/api/token-launch/'+ident+'/claim/prepare',json={},
            headers={'X-CSRF-Token':'test-csrf'})
    assert retry.status_code==200,retry.get_data(as_text=True)
    with sqlite3.connect(d.DB_FILE) as c:
        rows=c.execute('SELECT status,COUNT(*) FROM token_reward_claims GROUP BY status').fetchall()
    assert dict(rows)=={'failed':1,'prepared':1}
    print('PASS exact failed claim becomes terminal Failed and no longer blocks a safe retry')
    tmp.cleanup()


def test_recorded_submitted_signature_auto_settles_on_earnings_refresh():
    tmp,app,d,client,owner,ident,raw,built,signed=signed_fixture()
    wallet=str(owner.pubkey());sig=str(signed.signatures[0]);claim_id='b'*32
    with sqlite3.connect(d.DB_FILE) as c:
        c.execute("UPDATE token_launches SET reward_mode='community',quote_asset='SOL' WHERE id=?",(ident,))
        c.execute('''INSERT INTO token_reward_claims
          (id,launch_id,wallet,mint,quote_asset,reward_mode,accrued_raw,
           accrued_scope,transaction_b64,signature,status,created_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
          (claim_id,ident,wallet,built['mint'],'SOL','community','5000000',
           'sharing_config',raw,sig,'submitted',int(time.time())))
    signed_b64=base64.b64encode(bytes(signed)).decode();methods=[]
    def rpc(url,*,json,timeout):
        methods.append(json['method'])
        assert json['method']=='getTransaction'
        return Reply({'transaction':[signed_b64,'base64'],'meta':{'err':None}})
    with patch('token_launch.requests.post',side_effect=rpc):
        data=client.get('/api/token-launch/creator-earnings').get_json()
    assert data['pending_claims']==0 and data['confirmed_claims']==1
    assert data['history'][0]['status']=='confirmed'
    with sqlite3.connect(d.DB_FILE) as c:
        assert c.execute('SELECT status FROM token_reward_claims WHERE id=?',
                         (claim_id,)).fetchone()[0]=='confirmed'
    assert methods==['getTransaction'],'known signature should be checked directly, not wallet-scanned'
    print('PASS submitted Phantom signature auto-settles on earnings refresh without another approval')
    tmp.cleanup()


def test_two_simultaneous_prepare_requests_create_exactly_one_claim():
    tmp,app,d,_client,owner,ident,raw,built=fixture()
    wallet=str(owner.pubkey())
    clients=[app.test_client(),app.test_client()]
    for client in clients:
        with client.session_transaction() as sess:
            sess['wallet']=wallet;sess['csrf_token']='test-csrf'
    gate=Barrier(2)
    def rpc(url,*,json,timeout):
        return rpc_for_preparation(json)
    def builder(args,**kwargs):
        assert args[-1].endswith('build-reward-claim.cjs')
        gate.wait(timeout=8)
        return SimpleNamespace(returncode=0,stdout=json_module.dumps(built),stderr='')
    json_module=json
    def prepare(client):
        r=client.post('/api/token-launch/'+ident+'/claim/prepare',json={},
            headers={'X-CSRF-Token':'test-csrf'})
        return r.status_code,r.get_json()
    with patch.dict(os.environ,{'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'1'}),\
         patch('token_launch.requests.post',side_effect=rpc),\
         patch('token_launch.subprocess.run',side_effect=builder):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(prepare,clients))
    statuses=sorted(code for code,_ in results)
    assert statuses==[200,409],results
    with sqlite3.connect(d.DB_FILE) as c:
        rows=c.execute("SELECT id,status FROM token_reward_claims WHERE wallet=? AND status IN ('prepared','submitted')",
                       (wallet,)).fetchall()
    assert len(rows)==1 and rows[0][1]=='prepared',rows
    winner=next(body for code,body in results if code==200)
    loser=next(body for code,body in results if code==409)
    assert winner['claim_id']==rows[0][0]
    assert 'already pending' in loser['msg'].lower()
    print('PASS simultaneous Claim taps are serialized: one prepared claim, one 409, never two payable claims')
    tmp.cleanup()


if __name__=='__main__':
    test_exact_failed_claim_is_terminal_and_retryable()
    test_recorded_submitted_signature_auto_settles_on_earnings_refresh()
    test_two_simultaneous_prepare_requests_create_exactly_one_claim()
    print('ALL CREATOR CLAIM RELIABILITY REGRESSIONS PASSED')
