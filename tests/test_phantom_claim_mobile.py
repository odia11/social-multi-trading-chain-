"""Mobile claim signs only its exact prepared transaction, never a duplicate."""
import base64
import os
import sqlite3
import time
from urllib.parse import urlparse, parse_qs
from unittest.mock import patch
from cryptography.fernet import Fernet
from nacl.public import PrivateKey
from solders.hash import Hash
from solders.instruction import Instruction, AccountMeta
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction
from test_phantom_launch_mobile import setup, prepared_row, lookup, make_reply
import phantom_launch_mobile as mobile
import token_launch


def test_mobile_claim():
    with patch.dict(os.environ, {'ENCRYPTION_KEY':Fernet.generate_key().decode()}):
        with patch.dict(os.environ, {'ENCRYPTION_KEY':''}):
            tmp,app,d=setup()
        d.csrf_exempt=lambda fn:fn
        mobile.install(d,lambda ident,wallet:lookup(d,ident,wallet),
            lambda *args:False,lambda *args:True,lambda *args:True,
            lambda raw,**kwargs:True)
        owner=Keypair(); mint=Keypair()
        launch,_=prepared_row(d,owner,mint,'e')
        msg=Message.new_with_blockhash([Instruction(Pubkey.from_string(token_launch.PUMP_PROGRAM),
            b'claim-example',[AccountMeta(owner.pubkey(),True,True)])],owner.pubkey(),Hash.default())
        original=Transaction.new_unsigned(msg)
        claim_id='f'*32
        with sqlite3.connect(d.DB_FILE) as db:
            db.execute("UPDATE token_launches SET status='live' WHERE id=?",(launch,))
            db.execute('''INSERT INTO token_reward_claims
                (id,launch_id,wallet,mint,quote_asset,reward_mode,accrued_raw,accrued_scope,
                 transaction_b64,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (claim_id,launch,str(owner.pubkey()),str(mint.pubkey()),'USDC','creator',
                 '1000000','creator_wallet_all_tokens',base64.b64encode(bytes(original)).decode(),int(time.time())))
        phantom=PrivateKey.generate();pk=mobile.b58enc(bytes(phantom.public_key))
        assert mobile.remember_authenticated_session(d.DB_FILE,os.environ['ENCRYPTION_KEY'],
            str(owner.pubkey()),{'wallet_address':str(owner.pubkey()),'sk':bytes(phantom),
                                 'phantom_pk':pk,'session':'mock-session'})
        client=app.test_client();guest=app.test_client()
        with client.session_transaction() as sess:
            sess['wallet']=str(owner.pubkey());sess['csrf_token']='test-csrf'
        h={'X-CSRF-Token':'test-csrf'}
        path='/api/token-launch/'+launch+'/claim/phantom/start'
        assert client.post(path,json={'claim_id':claim_id}).status_code==403
        ready=client.post(path,json={'claim_id':claim_id,'return_to_pwa':True},headers=h)
        assert ready.status_code==200,ready.get_data(as_text=True)
        assert ready.get_json()['requires_connect'] is True
        q={k:v[0] for k,v in parse_qs(urlparse(ready.get_json()['url']).query).items()}
        callback=parse_qs(urlparse(q['redirect_link']).query)
        assert callback['action']==['claim'] and callback['pwa']==['1']
        assert callback['step']==['connect']
        connected_reply=make_reply(phantom,q['dapp_encryption_public_key'],
            {'public_key':str(owner.pubkey()),'session':'fresh-claim-session'})
        connected=guest.post('/api/phantom-launch/complete',json={
            'token':callback['token'][0],'step':'connect',
            'phantom_encryption_public_key':pk,**connected_reply})
        assert connected.status_code==200,connected.get_data(as_text=True)
        sq={k:v[0] for k,v in parse_qs(urlparse(connected.get_json()['url']).query).items()}
        sign_callback=parse_qs(urlparse(sq['redirect_link']).query)
        signed=Transaction.populate(msg,[owner.sign_message(bytes(msg))])
        response=make_reply(phantom,sq['dapp_encryption_public_key'],
            {'transaction':mobile.b58enc(bytes(signed))})
        relayed=[]
        def relay(raw,signature,endpoints,**kw):
            assert raw==bytes(signed) and signature==str(signed.signatures[0])
            relayed.append(signature)
            return False
        with patch('launch_delivery.relay_identical_signed',side_effect=relay):
            result=guest.post('/api/phantom-launch/complete',json={
                'token':callback['token'][0],'step':'sign',**response})
        assert result.status_code==200,result.get_data(as_text=True)
        assert result.get_json()['submitted'] and len(relayed)==1
        assert guest.post('/api/phantom-launch/complete',json={
            'token':callback['token'][0],'step':'sign',**response}).status_code==409
        assert client.post(path,json={'claim_id':claim_id},headers=h).status_code==409
        with patch('launch_delivery.relay_identical_signed',side_effect=relay):
            retry=client.post('/api/token-launch/'+launch+'/claim/phantom/retry-delivery',
                              json={'claim_id':claim_id},headers=h)
        assert retry.status_code==200 and not retry.get_json()['delivered']
        assert len(relayed)==2 and relayed[0]==relayed[1]
        with sqlite3.connect(d.DB_FILE) as db:
            assert db.execute('SELECT status,signature FROM token_reward_claims WHERE id=?',(claim_id,)).fetchone()==(
                'submitted',str(signed.signatures[0]))
        print('PASS mobile claim exact signature, replay protection, owner session and pending recovery')
        tmp.cleanup()

if __name__=='__main__':test_mobile_claim()
