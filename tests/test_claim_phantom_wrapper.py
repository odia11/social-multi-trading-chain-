"""Offline Phantom-injected wrapper and already-paid claim reconciliation.

Uses synthetic wallet/transactions and temporary SQLite. Never broadcasts,
accesses production DB, spends cryptocurrency or requires a private wallet.
"""
import base64
import os
import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import patch
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.hash import Hash
from solders.message import Message
from solders.instruction import Instruction,AccountMeta
from solders.transaction import Transaction
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_creator_rewards_preflight import fixture,Reply
import token_launch


def build_claim(owner,*,extra=True,bad_core=False,blockhash=None):
    wallet=owner.pubkey()
    usdc=Pubkey.from_string(token_launch.USDC_MINT)
    ata,_=Pubkey.find_program_address([bytes(wallet),
        bytes(Pubkey.from_string(token_launch.SPL_TOKEN_PROGRAM)),bytes(usdc)],
        Pubkey.from_string(token_launch.ASSOCIATED_TOKEN_PROGRAM))
    creator_vault=Pubkey.from_string('8LL7uiV7GGPTrGTGL8D3avaDfUVUpJuuJkFKQYTGfRYU')
    core=[Instruction(Pubkey.from_string(token_launch.ASSOCIATED_TOKEN_PROGRAM),
                     b'\x01',[AccountMeta(wallet,True,True),AccountMeta(ata,False,True)]),
          Instruction(Pubkey.from_string(token_launch.PUMP_PROGRAM),
                     b'\xcf\x11\x8a\xf2\x04\x22\x13\x38',
                     [AccountMeta(wallet,True,True),AccountMeta(ata,False,True),
                      AccountMeta(creator_vault,False,False),AccountMeta(usdc,False,False)])]
    bh=blockhash or Hash.default()
    unsigned=Transaction.new_unsigned(Message.new_with_blockhash(core,wallet,bh))
    if extra:
        compute=Pubkey.from_string(token_launch.COMPUTE_BUDGET_PROGRAM)
        phantom=Pubkey.from_string(token_launch.PHANTOM_CLAIM_WRAPPER)
        first=Instruction(compute,b'\x02'+(200000).to_bytes(4,'little'),[])
        second=Instruction(compute,b'\x03'+(375000).to_bytes(8,'little'),[])
        tail1=Instruction(phantom,b'\x06\x04\x03',[AccountMeta(wallet,True,False)])
        tail2=Instruction(phantom,b'\x0a\x04\x04',[AccountMeta(ata,False,True)])
        expanded=[first,second]+core+[tail1,tail2]
    else:expanded=core
    if bad_core:
        expanded[2 if extra else 0]=Instruction(Pubkey.from_string(token_launch.ASSOCIATED_TOKEN_PROGRAM),
                b'\x00',[AccountMeta(wallet,True,True),AccountMeta(ata,False,True)])
    msg=Message.new_with_blockhash(expanded,wallet,bh)
    signed=Transaction.populate(msg,[owner.sign_message(bytes(msg))])
    assert all(signed.verify_with_results())
    return unsigned,signed,ata


def test_recover_original_paid_and_repeated_zero_payout():
    tmp,app,d,client,owner,ident,_,_=fixture()
    wallet=str(owner.pubkey());now=int(time.time())
    one,paid,ata=build_claim(owner)
    two,empty,_=build_claim(owner,blockhash=Hash.from_string(str(Keypair().pubkey())))
    first='c'*32;second='d'*32
    with sqlite3.connect(d.DB_FILE) as c:
        for claim_id,raw,created in [(first,one,now-50),(second,two,now-20)]:
            c.execute('''INSERT INTO token_reward_claims
             (id,launch_id,wallet,mint,quote_asset,reward_mode,accrued_raw,
              accrued_scope,transaction_b64,created_at)
              VALUES (?,?,?,?,?,?,?,?,?,?)''',
              (claim_id,ident,wallet,str(Keypair().pubkey()),'USDC',
               'creator','3962289','creator_wallet_all_tokens',
               base64.b64encode(bytes(raw)).decode(),created))
    txs={str(paid.signatures[0]):(paid,now-42,3962289),
         str(empty.signatures[0]):(empty,now-12,0)}
    assert all(t.verify_with_results()==[True] for t,_,_ in txs.values())
    ata_address=str(ata)
    def fake_rpc(url,*,json,timeout):
        if url==d.SOLANA_RPC:
            return Reply(code=429,error={'code':429})
        method=json['method'];arg=json['params']
        if method=='getSignaturesForAddress':
            assert arg[0]==wallet
            return Reply([{'signature':sig,'blockTime':time_,'err':None}
                          for sig,(_,time_,_) in reversed(list(txs.items()))])
        assert method=='getTransaction'
        obj,time_,received=txs[arg[0]]
        if arg[1]['encoding']=='base64':
            pre=[5000000]*len(obj.message.account_keys)
            post=pre[:];post[0]-=1568440
            return Reply({'transaction':[base64.b64encode(bytes(obj)).decode(),'base64'],
                          'meta':{'err':None,'preBalances':pre,'postBalances':post}})
        assert arg[1]['encoding']=='json'
        keys=[str(k) for k in obj.message.account_keys];index=keys.index(ata_address)
        pre=[5000000]*len(keys);post=pre[:];post[0]-=1568440
        pre[index]=0 if received else 2039280
        result={'transaction':{'message':{'accountKeys':keys}},'meta':{
            'err':None,'preBalances':pre,'postBalances':post,
            'preTokenBalances':([] if received else [{
                'accountIndex':index,'owner':wallet,'mint':token_launch.USDC_MINT,
                'uiTokenAmount':{'decimals':6,'amount':'3962289'}}]),
            'postTokenBalances':[{'accountIndex':index,'owner':wallet,
                   'mint':token_launch.USDC_MINT,
                   'uiTokenAmount':{'decimals':6,'amount':'3962289'}}]}}
        return Reply(result)
    with patch('token_launch.requests.post',side_effect=fake_rpc),patch('token_launch.time.sleep'):
        rec=app._orca_reconcile_reward_claims()
    assert rec=={'checked':2,'recovered':1,'no_payout':1,'unavailable':0},rec
    with sqlite3.connect(d.DB_FILE) as c:
        rows=c.execute('SELECT id,status,received_raw,signature FROM token_reward_claims ORDER BY created_at').fetchall()
    assert rows[0]==(first,'confirmed','3962289',str(paid.signatures[0])),rows
    assert rows[1]==(second,'confirmed_no_payout','0',str(empty.signatures[0])),rows
    assert client.get('/api/token-launch/'+ident+'/claims').get_json()['claims'][0]['received_raw']=='0'
    with patch('token_launch.requests.post') as api:
        assert app._orca_reconcile_reward_claims()=={'checked':0,'recovered':0,'no_payout':0,'unavailable':0}
        assert api.call_count==0
    print('PASS Phantom wallet additions cannot erase actual creator claim: 3.962289 USDC on-chain recovered')
    print('PASS second successful transaction with 0 USDC is separately recorded as no-payout')
    print('PASS after reconciliation no second payout, signing or RPC retries occur')
    tmp.cleanup()


def test_reconcile_only_requested_wallet():
    tmp,app,d,client,owner,ident,raw,built=fixture()
    another=Keypair()
    with sqlite3.connect(d.DB_FILE) as c:
        c.execute('''INSERT INTO token_reward_claims
            (id,launch_id,wallet,mint,quote_asset,reward_mode,accrued_raw,
             accrued_scope,transaction_b64,created_at)
             VALUES (?,?,?,?,?,?,?,?,?,?)''',
             ('a'*32,ident,str(another.pubkey()),str(Keypair().pubkey()),'USDC',
              'creator','100','creator_wallet_all_tokens',raw,int(time.time())))
    def rpc(url,*,json,timeout):
        assert json['params'][0]!=str(another.pubkey()),'unrelated claim blocked this wallet'
        return Reply([])
    with patch('token_launch.requests.post',side_effect=rpc):
        outcome=app._orca_reconcile_reward_claims(str(owner.pubkey()))
    assert outcome=={'checked':0,'recovered':0,'no_payout':0,'unavailable':0}
    print('PASS another wallet’s unresolved claim cannot block this creator')
    tmp.cleanup()


def test_reject_modified_claim_cores_and_overspending():
    tmp,app,d,client,owner,ident,_,_=fixture()
    original,legit,ata=build_claim(owner)
    expected=base64.b64encode(bytes(original)).decode()
    base=dict(prepare_tx_b64=expected,wallet=str(owner.pubkey()),mint=str(Keypair().pubkey()))
    def check(signed,sol=1568440):
        sig=str(signed.signatures[0]);b64=base64.b64encode(bytes(signed)).decode()
        def fake(url,*,json,timeout):
            return Reply({'transaction':[b64,'base64'], 'meta':{
               'err':None,'preBalances':[5000000], 'postBalances':[5000000-sol]}})
        with patch('token_launch.requests.post',side_effect=fake):
            return client.post('/api/token-launch/'+ident+'/claim/confirm',json={
                 'claim_id':'f'*32,'signature':sig},headers={'X-CSRF-Token':'test-csrf'})
    # Route with no claim is not enough to test the cryptographic core:
    # build a matching temporary claim for each variant.
    with sqlite3.connect(d.DB_FILE) as c:
        c.execute('''INSERT INTO token_reward_claims
            (id,launch_id,wallet,mint,quote_asset,reward_mode,accrued_raw,accrued_scope,
             transaction_b64,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',
           ('f'*32,ident,str(owner.pubkey()),str(Keypair().pubkey()),'USDC',
            'creator','100','creator_wallet_all_tokens',expected,int(time.time())))
    _,tampered,_=build_claim(owner,bad_core=True)
    assert check(tampered).status_code==400
    assert 'does not match' in check(tampered).get_json()['msg']
    assert check(legit,sol=5_000_001).status_code==400
    with sqlite3.connect(d.DB_FILE) as c:
        assert c.execute('SELECT status FROM token_reward_claims WHERE id=?',('f'*32,)).fetchone()[0]=='prepared'
    print('PASS altered Pump/ATA core and fee-payer costs above the 0.005 SOL gate are rejected')
    tmp.cleanup()

if __name__=='__main__':
 test_recover_original_paid_and_repeated_zero_payout()
 test_reject_modified_claim_cores_and_overspending()
 test_reconcile_only_requested_wallet()
