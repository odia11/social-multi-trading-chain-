"""Phantom mobile-browser launch: connection, signed exact mint, idempotence.

Network and Phantom are mocked: no real Solana transaction is sent.
"""
import base64
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from unittest.mock import patch
from cryptography.fernet import Fernet
from nacl.public import Box,PrivateKey,PublicKey
from solders.hash import Hash
from solders.instruction import Instruction,AccountMeta
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_token_launch import setup,icon
import phantom_launch_mobile as mobile
import token_launch

def prepared_row(d,owner,mint,nonce):
    from solders.transaction import Transaction as Tx
    wallet=owner.pubkey()
    instruction=Instruction(Pubkey.from_string(token_launch.PUMP_PROGRAM),b'example',
        [AccountMeta(wallet,True,True),AccountMeta(mint.pubkey(),True,True)])
    msg=Message.new_with_blockhash([instruction],wallet,Hash.default())
    partial=Tx.new_unsigned(msg)
    partial.partial_sign([mint],Hash.default())
    launch_id=nonce*32
    with sqlite3.connect(d.DB_FILE) as db:
        db.execute("""INSERT INTO token_launches
          (id,wallet,client_nonce,name,symbol,icon_webp,reward_mode,
           quote_asset,mint,status,prepare_tx_b64,prepared_at,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (launch_id,str(wallet),'mobile-test-'+nonce,'Mobile Test','ORC',
           b'image','creator','USDC',str(mint.pubkey()),'prepared',
           base64.b64encode(bytes(partial)).decode(),int(time.time()),int(time.time())))
    return launch_id,partial

def make_reply(sk,server_pk,payload):
    sealed=Box(sk,PublicKey(mobile.b58dec(server_pk))).encrypt(json.dumps(payload).encode())
    return {'nonce':mobile.b58enc(sealed.nonce),'data':mobile.b58enc(sealed.ciphertext)}

def test_mobile_browser_handoff():
    with patch.dict(os.environ,{'ENCRYPTION_KEY':Fernet.generate_key().decode()}):
        with patch.dict(os.environ,{'ENCRYPTION_KEY':''}):
            tmp,app,d=setup()
        d.csrf_exempt=lambda fn:fn
        blockhash_ok=[True]
        mobile.install(d,lambda ident,wallet: lookup(d,ident,wallet),
            lambda *args:True,lambda *args:True,lambda *args:True,
            lambda _:blockhash_ok[0])
        user=Keypair();mint=Keypair()
        ident,partial=prepared_row(d,user,mint,'a')
        client=app.test_client()
        with client.session_transaction() as sess:
            sess['wallet']=str(user.pubkey());sess['csrf_token']='test-csrf'
        h={'X-CSRF-Token':'test-csrf'}
        start='/api/token-launch/'+ident+'/phantom/start'
        assert client.post(start,json={'stage':'create'}).status_code==403
        assert client.post(start,json={'stage':'weird'},headers=h).status_code==400
        response=client.post(start,json={'stage':'create'},headers=h)
        assert response.status_code==200,response.get_data(as_text=True)[:260]
        first=response.get_json()
        assert first['requires_connect']
        assert '/ul/v1/connect?' in first['url']
        assert 'ul/v1/signAndSendTransaction' not in first['url']
        params={k:v[0] for k,v in parse_qs(urlparse(first['url']).query).items()}
        callback=parse_qs(urlparse(params['redirect_link']).query)
        assert params['app_url']=='https://orcagent.fun'
        token=callback['token'][0]
        phantom=PrivateKey.generate()
        pk=mobile.b58enc(bytes(phantom.public_key))
        session='mock-phantom-session-no-secret'
        # Cross-browser callback has NO logged-in OrcAgent cookie.
        guest=app.test_client()
        wrong=make_reply(phantom,params['dapp_encryption_public_key'],
                         {'public_key':str(Keypair().pubkey()),'session':session})
        result=guest.post('/api/phantom-launch/complete',json={
             'token':token,'step':'connect',
             'phantom_encryption_public_key':pk,**wrong})
        assert result.status_code==409
        assert 'wallet differs' in result.get_json()['msg']
        correct=make_reply(phantom,params['dapp_encryption_public_key'],
                           {'public_key':str(user.pubkey()),'session':session})
        result=guest.post('/api/phantom-launch/complete',json={
            'token':token,'step':'connect','phantom_encryption_public_key':pk,**correct})
        assert result.status_code==200,result.get_data(as_text=True)[:260]
        sign_url=result.get_json()['url']
        assert '/ul/v1/signTransaction?' in sign_url
        sign_query={k:v[0] for k,v in parse_qs(urlparse(sign_url).query).items()}
        signed=Transaction.populate(partial.message,
                                    [user.sign_message(bytes(partial.message)),partial.signatures[1]])
        assert all(signed.verify_with_results())
        approval=make_reply(phantom,params['dapp_encryption_public_key'],
                            {'transaction':mobile.b58enc(bytes(signed))})
        seen=[]
        def fake_relay(raw,signature,endpoints):
            assert raw==bytes(signed)
            assert signature==str(signed.signatures[0])
            assert endpoints
            seen.append(signature)
            return True
        with patch('launch_delivery.relay_identical_signed',side_effect=fake_relay):
            final=guest.post('/api/phantom-launch/complete',json={
                'token':token,'step':'sign',**approval})
            assert final.status_code==200,final.get_data(as_text=True)[:260]
            assert final.get_json()['confirmed']
            assert final.get_json()['signature']==str(signed.signatures[0])
            repeated=guest.post('/api/phantom-launch/complete',json={
                'token':token,'step':'sign',**approval})
            assert repeated.status_code==409 and len(seen)==1
        with sqlite3.connect(d.DB_FILE) as db:
            row=db.execute('SELECT status,launch_signature,mint FROM token_launches WHERE id=?',
                           (ident,)).fetchone()
        assert row==('live',str(signed.signatures[0]),str(mint.pubkey()))
        # A verified mobile login also seeds the session cache: no extra
        # Phantom Connect prompt the first time an already logged-in user mints.
        other=Keypair()
        bad={'wallet_address':str(other.pubkey()),'sk':bytes(phantom),
             'phantom_pk':pk,'session':session}
        assert not mobile.remember_authenticated_session(d.DB_FILE,
             os.environ['ENCRYPTION_KEY'],str(user.pubkey()),bad)
        good={**bad,'wallet_address':str(user.pubkey())}
        assert mobile.remember_authenticated_session(d.DB_FILE,
             os.environ['ENCRYPTION_KEY'],str(user.pubkey()),good)
        # Subsequent tokens from the SAME account skip reconnect.
        second,part2=prepared_row(d,user,Keypair(),'b')
        again=client.post('/api/token-launch/'+second+'/phantom/start',
                          json={'stage':'create'},headers=h)
        assert again.status_code==200
        assert again.get_json()['requires_connect'] is False
        assert '/ul/v1/signTransaction?' in again.get_json()['url']
        next_query={k:v[0] for k,v in parse_qs(urlparse(again.get_json()['url']).query).items()}
        next_token=parse_qs(urlparse(next_query['redirect_link']).query)['token'][0]
        signed2=Transaction.populate(part2.message,
            [user.sign_message(bytes(part2.message)),part2.signatures[1]])
        # An expired blockhash must not be relayed.
        next_reply=make_reply(phantom,next_query['dapp_encryption_public_key'],
            {'transaction':mobile.b58enc(bytes(signed2))})
        blockhash_ok[0]=False
        expired_hash=guest.post('/api/phantom-launch/complete',json={
            'token':next_token,'step':'sign',**next_reply})
        assert expired_hash.status_code==409 and 'expired' in expired_hash.get_json()['msg']
        with sqlite3.connect(d.DB_FILE) as db:
            assert db.execute('SELECT status,launch_signature FROM token_launches WHERE id=?',
                              (second,)).fetchone()==('prepared','')
        blockhash_ok[0]=True
        # If Phantom revoked/expired that cached action session, the saved
        # token must recover on the next tap rather than looping forever.
        sign_params={k:v[0] for k,v in parse_qs(urlparse(again.get_json()['url']).query).items()}
        sign_return=parse_qs(urlparse(sign_params['redirect_link']).query)
        expired=guest.post('/api/phantom-launch/complete',json={
            'token':sign_return['token'][0],'step':'sign','errorCode':'4001'})
        assert expired.status_code==409
        third,_=prepared_row(d,user,Keypair(),'c')
        retry=client.post('/api/token-launch/'+third+'/phantom/start',
                          json={'stage':'create'},headers=h)
        assert retry.status_code==200 and retry.get_json()['requires_connect'] is True
        print('PASS mobile Phantom signTransaction, exact signed-byte RPC relay')
        print('PASS mobile Phantom connect once, then direct approval in original browser')
        print('PASS exact mint co-signature, replay guard, cross-browser callback, no double broadcast')
        tmp.cleanup()

def lookup(d,ident,wallet):
    with sqlite3.connect(d.DB_FILE) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT * FROM token_launches WHERE id=? AND wallet=?',
                       (ident,wallet)).fetchone()
    return dict(row) if row else None

if __name__=='__main__':
    test_mobile_browser_handoff()
