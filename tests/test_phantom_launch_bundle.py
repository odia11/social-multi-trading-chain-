"""Offline Phantom signAllTransactions launch handoff test."""
import base64
import json
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from cryptography.fernet import Fernet
from nacl.public import Box, PrivateKey, PublicKey
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tests'))
from test_token_launch import setup
from test_phantom_launch_mobile import prepared_row, make_reply, lookup
import phantom_launch_mobile as mobile
import token_launch


def test_bundle():
    key=Fernet.generate_key().decode()
    with patch.dict(os.environ,{'ENCRYPTION_KEY':key}):
        with patch.dict(os.environ,{'ENCRYPTION_KEY':''}):
            tmp,app,d=setup()
        d.csrf_exempt=lambda fn:fn
        user,mint=Keypair(),Keypair()
        ident,create=prepared_row(d,user,mint,'e')

        ix=Instruction(Pubkey.from_string(token_launch.PUMP_PROGRAM),b'fee-share',
                       [AccountMeta(user.pubkey(),True,True)])
        msg=Message.new_with_blockhash([ix],user.pubkey(),Hash.default())
        finalize=Transaction.new_unsigned(msg)
        with sqlite3.connect(d.DB_FILE) as db:
            db.execute('UPDATE token_launches SET finalize_tx_b64=? WHERE id=?',
                       (base64.b64encode(bytes(finalize)).decode(),ident))

        seen=[]
        def one_submit(row,txs):
            signed=[Transaction.from_bytes(base64.b64decode(x)) for x in txs]
            assert len(signed)==2 and all(all(tx.verify_with_results()) for tx in signed)
            assert bytes(signed[0].message)==bytes(create.message)
            assert bytes(signed[1].message)==bytes(finalize.message)
            seen.extend(signed)
            return {'ok':True,'confirmed':True,'live':True,
                    'create_signature':str(signed[0].signatures[0]),
                    'finalize_signature':str(signed[1].signatures[0]),
                    'msg':'Token launch confirmed. Your token is live on OrcAgent.'}

        mobile.install(d,lambda i,w:lookup(d,i,w),lambda *a:True,lambda *a:True,
                       lambda *a:True,lambda *a:True,None,one_submit)

        phantom=PrivateKey.generate()
        phantom_pk=mobile.b58enc(bytes(phantom.public_key))
        session='bundle-session'
        record={'wallet_address':str(user.pubkey()),'sk':bytes(PrivateKey.generate()),
                'phantom_pk':phantom_pk,'session':session}
        assert mobile.remember_authenticated_session(d.DB_FILE,key,str(user.pubkey()),record)

        client=app.test_client()
        with client.session_transaction() as sess:
            sess['wallet']=str(user.pubkey());sess['csrf_token']='test-csrf'
        start=client.post('/api/token-launch/'+ident+'/phantom/start',
                          json={'stage':'bundle','return_to_pwa':True},
                          headers={'X-CSRF-Token':'test-csrf'})
        assert start.status_code==200,start.get_data(as_text=True)
        data=start.get_json()
        assert data['requires_connect'] is False
        assert '/ul/v1/signAllTransactions?' in data['url']

        q={k:v[0] for k,v in parse_qs(urlparse(data['url']).query).items()}
        server_pk=PublicKey(mobile.b58dec(q['dapp_encryption_public_key']))
        payload=json.loads(Box(phantom,server_pk).decrypt(
            mobile.b58dec(q['data']) if 'data' in q else mobile.b58dec(q['payload']),
            mobile.b58dec(q['nonce'])))
        assert payload['session']==session and len(payload['transactions'])==2

        signed_create=Transaction.populate(create.message,[
            user.sign_message(bytes(create.message)),create.signatures[1]])
        signed_final=Transaction.populate(finalize.message,[
            user.sign_message(bytes(finalize.message))])
        callback=parse_qs(urlparse(q['redirect_link']).query)
        token=callback['token'][0]
        response=make_reply(phantom,q['dapp_encryption_public_key'],{
            'transactions':[mobile.b58enc(bytes(signed_create)),
                            mobile.b58enc(bytes(signed_final))]})
        guest=app.test_client()
        done=guest.post('/api/phantom-launch/complete',json={
            'token':token,'step':'sign',**response})
        assert done.status_code==200,done.get_data(as_text=True)
        assert done.get_json()['live'] is True and len(seen)==2
        print('PASS mobile launch uses Phantom signAllTransactions for one approval')
        print('PASS callback returns both exact signed transactions to OrcAgent')
        tmp.cleanup()


if __name__=='__main__':
    test_bundle()
