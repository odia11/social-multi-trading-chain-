"""No-network regression of the creator-USDC pilot: RPC 429 rescue, rent
refusal, exact unsigned claim preparation and confirmed recipient delta.
Never signs, broadcasts, spends SOL/USDC or accesses production DB.
"""
import base64
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import transfer,TransferParams
from solders.transaction import Transaction
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_token_launch import setup
import token_launch

class Reply:
    def __init__(self,result=None,code=200,error=None):
        self.status_code=code
        self.content={'error':error} if error else {'result':result}
    def json(self):return self.content
    def raise_for_status(self):pass


def fixture():
    tmp,app,d=setup();client=app.test_client();owner=Keypair()
    wallet=str(owner.pubkey());mint=str(Keypair().pubkey());ident='e'*32
    with sqlite3.connect(d.DB_FILE) as c:
        c.execute('''INSERT INTO token_launches
         (id,wallet,client_nonce,name,symbol,icon_webp,reward_mode,quote_asset,
          mint,status,launch_signature,created_at)
         VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
         (ident,wallet,'claim-test','Test','TEST',b'icon','creator','USDC',
          mint,'live','x'*88,int(time.time())))
    with client.session_transaction() as ss:
        ss['wallet']=wallet;ss['csrf_token']='test-csrf'
    tx=Transaction.new_unsigned(Message.new_with_blockhash([
        transfer(TransferParams(from_pubkey=owner.pubkey(),
                to_pubkey=owner.pubkey(),lamports=0))],owner.pubkey(),Hash.default()))
    raw=base64.b64encode(bytes(tx)).decode()
    built=dict(mint=mint,quote_mint=token_launch.USDC_MINT,
         transaction_b64=raw,transaction_bytes=len(bytes(tx)),
         accrued_raw='3962289',accrued_scope='creator_wallet_all_tokens')
    return tmp,app,d,client,owner,ident,raw,built


def test_claim_preflight_handles_429_and_wallet_rent_safely():
    tmp,app,d,client,owner,ident,raw,built=fixture()
    route='/api/token-launch/'+ident
    headers={'X-CSRF-Token':'test-csrf'}
    calls=[];state={'before':890880,'after':0,'err':'InsufficientFundsForFee'}
    def rpc(url,*,json,timeout):
        method=json['method'];calls.append((url,method))
        if url=='https://rpc.test.invalid':return Reply(code=429,error={'code':429})
        assert url=='https://solana-rpc.publicnode.com'
        if method=='getSignaturesForAddress':return Reply([])
        if method=='getLatestBlockhash':return Reply({'value':{'blockhash':str(Hash.default())}})
        if method=='getBalance':return Reply({'value':state['before']})
        if method=='getFeeForMessage':return Reply({'value':5000})
        if method=='simulateTransaction':return Reply({'value':{
          'err':state['err'],'accounts':[{'lamports':state['after']}],
          'logs':['Transfer: insufficient lamports 885880, need 1488440'] if state['err'] else []}})
        raise AssertionError('Claim tried unsafe RPC method '+method)
    def unsigned_builder(args,**kwargs):
        assert args[-1].endswith('build-reward-claim.cjs')
        assert kwargs['env']['ORCA_LAUNCH_RPC']=='https://solana-rpc.publicnode.com'
        assert kwargs['input'] and json.loads(kwargs['input'])['wallet']==str(owner.pubkey())
        return SimpleNamespace(returncode=0,stdout=json.dumps(built),stderr='')
    flags={'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'0',
           'ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_ENABLED':'1',
           'ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_WALLETS':str(owner.pubkey())}
    with patch.dict(os.environ,flags),patch('token_launch.requests.post',side_effect=rpc),\
         patch('token_launch.subprocess.run',side_effect=unsigned_builder),\
         patch('token_launch.time.sleep'):
        refusal=client.post(route+'/claim/prepare',json={},headers=headers)
        assert refusal.status_code==503,refusal.get_data(as_text=True)[:200]
        assert 'Insufficient SOL' in refusal.get_json()['msg']
        assert 'claim fees' in refusal.get_json()['msg']
        assert 'No transaction was sent' in refusal.get_json()['msg']
        assert 'transaction_b64' not in refusal.get_json()
        with sqlite3.connect(d.DB_FILE) as c:
            assert c.execute('SELECT COUNT(*) FROM token_reward_claims').fetchone()[0]==0
        state.update(before=5000000,after=3000000,err=None)
        approved=client.post(route+'/claim/prepare',json={},headers=headers)
        assert approved.status_code==200,approved.get_data(as_text=True)[:200]
        j=approved.get_json()
        assert j['pilot_estimated_max_sol_lamports']==2005000
        assert j['accrued_raw']=='3962289'
        assert j['accrued_scope']=='creator_wallet_all_tokens'
        assert not all(Transaction.from_bytes(base64.b64decode(j['transaction_b64'])).verify_with_results())
        with sqlite3.connect(d.DB_FILE) as c:
            assert c.execute('SELECT COUNT(*) FROM token_reward_claims').fetchone()[0]==1
        duplicate=client.post(route+'/claim/prepare',json={},headers=headers)
        assert duplicate.status_code==409 and 'already' in duplicate.get_json()['msg']
    assert not any(m in ('sendTransaction','sendRawTransaction','requestAirdrop') for _,m in calls)
    assert ('https://solana-rpc.publicnode.com','simulateTransaction') in calls
    print('PASS HTTP 429 claim preflight falls back to fixed read-only RPC, never sends any transaction')
    print('PASS insufficient creator USDC ATA rent gives 503 and writes no pending claim')
    print('PASS sufficient simulation enforces 0.005 SOL cap and returns only unsigned Phantom transaction')
    tmp.cleanup()


def test_received_usdc_is_exact_confirmed_wallet_delta_not_fee_snapshot():
    tmp,app,d,client,owner,ident,raw,built=fixture()
    wallet=str(owner.pubkey());route='/api/token-launch/'+ident
    claim_id='a'*32
    partial=Transaction.from_bytes(base64.b64decode(raw))
    signed=Transaction.populate(partial.message,[owner.sign_message(bytes(partial.message))])
    assert all(signed.verify_with_results())
    sig=str(signed.signatures[0]);signed_b64=base64.b64encode(bytes(signed)).decode()
    with sqlite3.connect(d.DB_FILE) as c:
        c.execute('''INSERT INTO token_reward_claims
          (id,launch_id,wallet,mint,quote_asset,reward_mode,accrued_raw,accrued_scope,
           transaction_b64,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',
           (claim_id,ident,wallet,built['mint'],'USDC','creator','3962289',
           'creator_wallet_all_tokens',raw,int(time.time())))
    owner_pk=Pubkey.from_string(wallet)
    ata,_=Pubkey.find_program_address([bytes(owner_pk),
      bytes(Pubkey.from_string(token_launch.SPL_TOKEN_PROGRAM)),
      bytes(Pubkey.from_string(token_launch.USDC_MINT))],
      Pubkey.from_string(token_launch.ASSOCIATED_TOKEN_PROGRAM))
    meta={'err':None,'preTokenBalances':[], 'postTokenBalances':[], 'preBalances':[10000000,0]}
    seen=[]
    def rpc(url,*,json,timeout):
        assert json['method']=='getTransaction'
        seen.append(json['params'][1]['encoding'])
        if url=='https://rpc.test.invalid':return Reply(code=429,error={'code':429})
        if json['params'][1]['encoding']=='base64':
            return Reply({'transaction':[signed_b64,'base64'],'meta':{'err':None}})
        return Reply({'transaction':{'message':{'accountKeys':[wallet,str(ata)]}},'meta':meta})
    body={'claim_id':claim_id,'signature':sig}
    with patch('token_launch.requests.post',side_effect=rpc),patch('token_launch.time.sleep'):
        missing=client.post(route+'/claim/confirm',json=body,
                   headers={'X-CSRF-Token':'test-csrf'})
        assert missing.status_code==503,missing.get_data(as_text=True)[:300]
        assert 'delta unavailable' in missing.get_json()['msg']
        with sqlite3.connect(d.DB_FILE) as c:
            assert c.execute('SELECT status,received_raw FROM token_reward_claims WHERE id=?',
                     (claim_id,)).fetchone()==('prepared','')
        # A lookalike USDC credit to somebody else must never be presented
        # as money received by this creator's wallet.
        meta['postTokenBalances']=[dict(accountIndex=1,
            mint=token_launch.USDC_MINT,owner=str(Keypair().pubkey()),
            uiTokenAmount={'amount':'9999999','decimals':6})]
        stranger=client.post(route+'/claim/confirm',json=body,
                    headers={'X-CSRF-Token':'test-csrf'})
        assert stranger.status_code==503 and 'received_raw' not in stranger.get_json()
        # Missing token pre-balance from a PREEXISTING account is not a
        # license to credit its whole balance as newly received creator fees.
        meta['preBalances']=[10000000,2039280]
        existing=client.post(route+'/claim/confirm',json=body,
                   headers={'X-CSRF-Token':'test-csrf'})
        assert existing.status_code==503 and 'received_raw' not in existing.get_json()
        meta['preBalances']=[10000000,0]
        # In a newly created recipient ATA, there is no preTokenBalance.
        # The actual confirmed postTokenBalance, NOT accrued_raw, is credited.
        meta['postTokenBalances']=[dict(
            accountIndex=1,mint=token_launch.USDC_MINT,owner=wallet,
            uiTokenAmount={'amount':'1250000','decimals':6})]
        confirmed=client.post(route+'/claim/confirm',json=body,
                    headers={'X-CSRF-Token':'test-csrf'})
        assert confirmed.status_code==200,confirmed.get_data(as_text=True)[:300]
        assert confirmed.get_json()['received_raw']=='1250000'
        assert confirmed.get_json()['confirmed'] is True
        with sqlite3.connect(d.DB_FILE) as c:
            assert c.execute('SELECT status,received_raw FROM token_reward_claims WHERE id=?',
                      (claim_id,)).fetchone()==('confirmed','1250000')
        history=client.get(route+'/claims').get_json()['claims']
        assert history[0]['received_raw']=='1250000'
        again=client.post(route+'/claim/confirm',json=body,headers={'X-CSRF-Token':'test-csrf'})
        assert again.status_code==200 and again.get_json()['received_raw']=='1250000'
        with client.session_transaction() as sess:sess['wallet']=str(Keypair().pubkey())
        assert client.get(route+'/claims').status_code==404
    assert 'base64' in seen and 'json' in seen
    print('PASS exact signed claim plus USDC recipient delta required before confirming payout')
    print('PASS another recipient or missing pre-existing balance cannot masquerade as newly received creator USDC')
    print('PASS wallet actually receives 1.25 USDC, not 3.962289 USDC vault snapshot')
    print('PASS claim history private, confirmed receipt idempotent, unrelated wallets denied')
    tmp.cleanup()

if __name__=='__main__':
 test_claim_preflight_handles_429_and_wallet_rent_safely()
 test_received_usdc_is_exact_confirmed_wallet_delta_not_fee_snapshot()
