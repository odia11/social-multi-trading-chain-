"""Phantom mainnet delivery fallback and safe expired-signature recovery.

All RPC calls mocked. No broadcast, mainnet spend, or creator credentials.
"""
import base64,os,sqlite3,sys
from pathlib import Path
from unittest.mock import patch
from solders.keypair import Keypair
from solders.transaction import Transaction
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_token_launch import setup
from test_phantom_launch_mobile import prepared_row
import launch_recovery,launch_delivery

class Result:
    def __init__(self,value=None,code=200):
        self.value=value;self.status_code=code
    def raise_for_status(self):
        if self.status_code!=200:
            raise __import__('requests').HTTPError('RPC unavailable')
    def json(self):return {'jsonrpc':'2.0','result':self.value}

def test_recover_expired():
    tmp,app,d=setup();c=app.test_client()
    user=Keypair();mint=Keypair();ident,part=prepared_row(d,user,mint,'a')
    sig=str(user.sign_message(bytes(part.message)))
    with c.session_transaction() as s:s['wallet']=str(user.pubkey());s['csrf_token']='test-csrf'
    head={'X-CSRF-Token':'test-csrf'}
    with sqlite3.connect(d.DB_FILE) as db:
        db.execute("UPDATE token_launches SET status='submitted', launch_signature=? WHERE id=?",(sig,ident))
    path='/api/token-launch/'+ident+'/recover-submitted'
    seen=[]
    def gone(url,*,json,timeout):
        meth=json['method'];seen.append((url,meth))
        if meth=='getSignatureStatuses':return Result({'value':[None]})
        if meth=='isBlockhashValid':return Result({'value':False})
        if meth=='getAccountInfo':return Result({'value':None})
        raise AssertionError('Recovery is read-only')
    with patch('launch_recovery.requests.post',side_effect=gone),          patch('token_launch.subprocess.run') as builder:
        assert c.post(path,json={}).status_code==403
        with c.session_transaction() as s:s['wallet']=str(Keypair().pubkey())
        assert c.post(path,json={},headers=head).status_code==404
        with c.session_transaction() as s:s['wallet']=str(user.pubkey())
        response=c.post(path,json={},headers=head)
        assert response.status_code==200,response.get_data(as_text=True)
        assert response.get_json()['recovered']
        assert c.post(path,json={},headers=head).status_code==409
        builder.assert_not_called()
    assert len({url for url,m in seen})>=2
    with sqlite3.connect(d.DB_FILE) as db:
        row=db.execute('SELECT status,mint,prepare_tx_b64,launch_signature,client_nonce FROM token_launches WHERE id=?',(ident,)).fetchone()
        audit=db.execute('SELECT old_mint,old_signature FROM token_launch_recovery_audit WHERE launch_id=?',(ident,)).fetchone()
    assert row==('draft',None,'','','mobile-test-a')
    assert audit==(str(mint.pubkey()),sig)
    print('PASS expired Phantom signature is safely recovered as SAME unsent draft only; old signature audited')
    tmp.cleanup()

def test_no_recovery_if_exists_or_unavailable():
    for blocker in ('signature','mint','blockhash','one_rpc'):
        tmp,app,d=setup();c=app.test_client()
        user=Keypair();mint=Keypair();ident,part=prepared_row(d,user,mint,'b')
        sig=str(user.sign_message(bytes(part.message)))
        with c.session_transaction() as s:s['wallet']=str(user.pubkey());s['csrf_token']='test-csrf'
        with sqlite3.connect(d.DB_FILE) as db:db.execute("UPDATE token_launches SET status='submitted',launch_signature=? WHERE id=?",(sig,ident))
        def response(url,*,json,timeout):
            meth=json['method']
            if blocker=='one_rpc' and url!='https://rpc.test.invalid':return Result(code=429)
            if meth=='getSignatureStatuses':
                return Result({'value':[{'err':None,'confirmationStatus':'finalized'} if blocker=='signature' else None]})
            if meth=='isBlockhashValid':return Result({'value':blocker=='blockhash'})
            if meth=='getAccountInfo':return Result({'value':{'owner':'system'} if blocker=='mint' else None})
            raise AssertionError('Forbidden action')
        with patch('launch_recovery.requests.post',side_effect=response):
            refused=c.post('/api/token-launch/'+ident+'/recover-submitted',
                           json={},headers={'X-CSRF-Token':'test-csrf'})
            assert refused.status_code==409,(blocker,refused.get_data(as_text=True))
        with sqlite3.connect(d.DB_FILE) as db:
            assert db.execute('SELECT status,launch_signature FROM token_launches WHERE id=?',
                              (ident,)).fetchone()==('submitted',sig)
        tmp.cleanup()
    print('PASS existing tx, onchain mint, valid blockhash or single RPC never cleared or duplicated')

def test_exact_relay_failover():
    user=Keypair();mint=Keypair()
    from solders.message import Message
    from solders.hash import Hash
    from solders.instruction import Instruction,AccountMeta
    from solders.pubkey import Pubkey
    msg=Message.new_with_blockhash([Instruction(Pubkey.default(),b'\x00',
                  [AccountMeta(mint.pubkey(),True,False)])],user.pubkey(),Hash.default())
    tx=Transaction.populate(msg,[user.sign_message(bytes(msg)),mint.sign_message(bytes(msg))])
    signature=str(tx.signatures[0])
    seen=[]
    def server(url,*,json,timeout):
        seen.append((url,json))
        if url=='https://first':return Result(code=429)
        return Result(signature)
    with patch('launch_delivery.requests.post',side_effect=server):
        assert launch_delivery.relay_identical_signed(bytes(tx),signature,
                     ('https://first','https://second','https://third'))
    assert len(seen)==2
    assert all(x[1]['method']=='sendTransaction' for x in seen)
    assert all(base64.b64decode(x[1]['params'][0])==bytes(tx) for x in seen)
    assert all(x[1]['params'][1]['skipPreflight'] is False for x in seen)
    assert all(x[1]['params'][1]['preflightCommitment']=='confirmed' for x in seen)
    with patch('launch_delivery.requests.post') as send:
        try:launch_delivery.relay_identical_signed(bytes(tx),str(mint.sign_message(bytes(msg))),('https://first',))
        except ValueError:pass
        else:raise AssertionError('Forged signature relayed')
        send.assert_not_called()
    print('PASS RPC 429 relays identical user-approved signed bytes, never skips preflight or signs')

if __name__=='__main__':
    test_recover_expired()
    test_no_recovery_if_exists_or_unavailable()
    test_exact_relay_failover()
