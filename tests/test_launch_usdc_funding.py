"""No-network USDC-only launch funding regressions (two Phantom approvals).

No real wallet, secret, Jupiter call, Solana broadcast, mint or swap.
"""
import base64
import os
import sqlite3
from decimal import Decimal
import sys
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_token_launch import setup,icon
import token_launch_usdc_funding as funding
from solders.hash import Hash
from solders.instruction import AccountMeta,Instruction
from solders.keypair import Keypair
from solders.message import MessageV0,to_bytes_versioned
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

class Response:
    status_code=200
    def __init__(self,payload):self.payload=payload
    def raise_for_status(self):pass
    def json(self):return self.payload

def make_quote(wallet,payer,amount=20_000_000,output=100_000_000):
    # Fake Jupiter message: payer is a different signer; user's signature
    # must be added by Phantom, never by OrcAgent.
    msg=MessageV0.try_compile(payer.pubkey(),
        [Instruction(Pubkey.default(),b'\x00',
                     [AccountMeta(wallet.pubkey(),True,False)])],[],Hash.default())
    unsigned=VersionedTransaction.populate(msg,[Signature.default(),Signature.default()])
    return {'transaction':base64.b64encode(bytes(unsigned)).decode(),
        'requestId':'mock-jupiter-request-01','inAmount':str(amount),
        'outAmount':str(output),'gasless':True,
        'signatureFeePayer':str(payer.pubkey())},msg

def test_funding():
    tmp,app,d=setup();client=app.test_client();user=Keypair()
    payer=Keypair();wallet=str(user.pubkey())
    with client.session_transaction() as s:
        s['wallet']=wallet;s['csrf_token']='test-csrf'
    h={'X-CSRF-Token':'test-csrf'}
    body={'name':'Gasless funding','symbol':'USDCX','client_nonce':'usdc-only-launch-00001',
          'image_data':icon(),'reward_mode':'creator','quote_asset':'USDC'}
    draft=client.post('/api/token-launch/draft',json=body,headers=h).get_json()['draft']
    path='/api/token-launch/'+draft['id']+'/fund/'
    with patch('token_launch_usdc_funding.requests.post',side_effect=__import__('requests').RequestException):
        assert client.get(path+'status').status_code==503  # never fabricate funding readiness
    with client.session_transaction() as s:s['wallet']=str(Keypair().pubkey())
    assert client.get(path+'status').status_code==404
    assert client.post(path+'quote',json={'amount_usdc':'20'},headers=h).status_code==404
    with client.session_transaction() as s:s['wallet']=wallet
    def provider(url,*,json,timeout,headers=None):
        if json.get('method')=='getBalance':return Response({'result':{'value':0}})
        assert url=='https://api.jup.ag/swap/v2/execute'
        return Response({'status':'Pending','signature':''})
    with patch.dict(os.environ,{'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'1','JUPITER_API_KEY':'mock'}), \
         patch('token_launch_usdc_funding.requests.get') as get, \
         patch('token_launch_usdc_funding.requests.post',side_effect=provider) as post:
        order,msg=make_quote(user,payer)
        get.return_value=Response(order)
        assert client.post(path+'quote',json={'amount_usdc':'20'},headers={}).status_code==403
        assert client.post(path+'quote',json={'amount_usdc':'0.1'},headers=h).status_code==400
        quoted=client.post(path+'quote',json={'amount_usdc':'20'},headers=h)
        assert quoted.status_code==200,quoted.get_data(as_text=True)[:210]
        data=quoted.get_json()
        assert data['target_sol']=='0.060000000'
        assert data['expected_sol']=='0.100000000'
        reused=client.post(path+'quote',json={'amount_usdc':'20'},headers=h)
        assert reused.status_code==200 and reused.get_json()['quote_id']==data['quote_id']
        assert get.call_count==1
        wrong=client.post(path+'execute',json={'quote_id':data['quote_id'],
                                'signed_transaction_b64':data['transaction_b64']},headers=h)
        assert wrong.status_code==400
        assert all(call.args[0]!='https://api.jup.ag/swap/v2/execute' for call in post.call_args_list)
        original=VersionedTransaction.from_bytes(base64.b64decode(data['transaction_b64']))
        keys=list(original.message.account_keys)[:original.message.header.num_required_signatures]
        signatures=list(original.signatures)
        signatures[keys.index(user.pubkey())]=user.sign_message(to_bytes_versioned(msg))
        signed=VersionedTransaction.populate(msg,signatures)
        signed_b64=base64.b64encode(bytes(signed)).decode()
        response=client.post(path+'execute',json={'quote_id':data['quote_id'],
                         'signed_transaction_b64':signed_b64},headers=h)
        assert response.status_code==200,response.get_data(as_text=True)
        executes=[call for call in post.call_args_list if call.args[0]=='https://api.jup.ag/swap/v2/execute']
        assert len(executes)==1
        assert executes[0].kwargs['json']['requestId']=='mock-jupiter-request-01'
        assert client.post(path+'execute',json={'quote_id':data['quote_id'],
                         'signed_transaction_b64':signed_b64},headers=h).status_code==409
        assert client.post(path+'quote',json={'amount_usdc':'20'},headers=h).status_code==409
        with sqlite3.connect(d.DB_FILE) as db:
            token=db.execute('SELECT status,mint,launch_signature FROM token_launches WHERE id=?',(draft['id'],)).fetchone()
            paid=db.execute('SELECT status FROM token_launch_funding WHERE launch_id=?',(draft['id'],)).fetchone()
        assert token==('draft',None,'') and paid==('submitted',)
        print('PASS user-only USDC gasless funding quotes, no duplicate quote/submission or automatic mint')
    tmp.cleanup()


def test_reject_false_gasless():
    tmp,app,d=setup();client=app.test_client();user=Keypair();payer=Keypair()
    with client.session_transaction() as s:s['wallet']=str(user.pubkey());s['csrf_token']='test-csrf'
    h={'X-CSRF-Token':'test-csrf'}
    body={'name':'Quote check','symbol':'TEST','client_nonce':'non-gasless-launch-001',
          'image_data':icon(),'reward_mode':'creator','quote_asset':'USDC'}
    draft=client.post('/api/token-launch/draft',json=body,headers=h).get_json()['draft']
    route='/api/token-launch/'+draft['id']+'/fund/quote'
    with patch.dict(os.environ,{'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'1','JUPITER_API_KEY':'mock'}), \
         patch('token_launch_usdc_funding.requests.post',return_value=Response({'result':{'value':0}})), \
         patch('token_launch_usdc_funding.requests.get') as get:
        order,_=make_quote(user,payer,output=40_000_000)
        get.return_value=Response(order)
        insufficient=client.post(route,json={'amount_usdc':'20'},headers=h)
        assert insufficient.status_code==409
        good,_=make_quote(user,payer)
        good['gasless']=False;get.return_value=Response(good)
        assert client.post(route,json={'amount_usdc':'20'},headers=h).status_code==503
        good['gasless']=True;good['signatureFeePayer']=str(user.pubkey())
        assert client.post(route,json={'amount_usdc':'20'},headers=h).status_code==503
        with sqlite3.connect(d.DB_FILE) as db:
            assert db.execute('SELECT COUNT(*) FROM token_launch_funding').fetchone()[0]==0
        print('PASS insufficient reserve, fake gasless and user-paid fee payer fail closed')
    tmp.cleanup()


def test_automatic_usdc_budget_quotes_live_sol_cost():
    tmp,app,d=setup();client=app.test_client()
    user=Keypair();payer=Keypair()
    with client.session_transaction() as s:
        s['wallet']=str(user.pubkey());s['csrf_token']='test-csrf'
    h={'X-CSRF-Token':'test-csrf'}
    body={'name':'Auto budget','symbol':'AUTO','client_nonce':'auto-budget-launch-0001',
          'image_data':icon(),'reward_mode':'creator','quote_asset':'USDC'}
    draft=client.post('/api/token-launch/draft',json=body,headers=h).get_json()['draft']
    route='/api/token-launch/'+draft['id']+'/fund/quote'
    seen=[]
    def quote(url,*,params,headers,timeout):
        seen.append(params)
        if 'taker' not in params:
            return Response({'outAmount':'50000000'})  # $10 = 0.05 SOL
        order,_=make_quote(user,payer,amount=int(params['amount']))
        return Response(order)
    with patch.dict(os.environ,{'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'1','JUPITER_API_KEY':'mock'}), \
         patch('token_launch_usdc_funding.requests.post',return_value=Response({'result':{'value':0}})), \
         patch('token_launch_usdc_funding.requests.get',side_effect=quote):
        too_low=client.post(route,json={'max_usdc':'12'},headers=h)
        assert too_low.status_code==409 and 'more USDC' in too_low.get_json()['msg']
        acceptable=client.post(route,json={'max_usdc':'25'},headers=h)
        assert acceptable.status_code==200,acceptable.get_data(as_text=True)[:250]
        data=acceptable.get_json()
        assert 15_000_000<int(Decimal(data['amount_usdc'])*1_000_000)<=25_000_000
        assert seen[0]['amount']=='10000000'
        assert all(p['inputMint']==funding.USDC and p['outputMint']==funding.SOL for p in seen)
        assert sum('taker' not in p for p in seen)==2
        print('PASS live SOL reserve pricing chooses bounded USDC automatically; max budget enforced')
    tmp.cleanup()


if __name__=='__main__':
    test_funding()
    test_reject_false_gasless()
    test_automatic_usdc_budget_quotes_live_sol_cost()
