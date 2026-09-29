"""Offline regression: SOL creator claims must use claim RPC fallbacks.

No network, signing, broadcasting, production DB, or funds are used.
"""
import base64,json,os,sqlite3,sys,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from flask import session
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.system_program import transfer,TransferParams
from solders.transaction import Transaction

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_token_launch import setup
import token_launch

class Reply:
    def __init__(self,result=None,code=200,error=None):
        self.status_code=code;self._result=result;self._error=error
    def json(self):
        return {'error':self._error} if self._error else {'result':self._result}
    def raise_for_status(self):
        if self.status_code>=400: raise RuntimeError('http '+str(self.status_code))

def test_sol_creator_claim_uses_claim_rpc_pool():
    tmp,app,d=setup();client=app.test_client();owner=Keypair()
    wallet=str(owner.pubkey());mint=str(Keypair().pubkey());ident='9'*32
    d.CLAIM_SOL_RPCS=['https://claim-a.invalid']
    with sqlite3.connect(d.DB_FILE) as c:
        c.execute("""INSERT INTO token_launches
          (id,wallet,client_nonce,name,symbol,icon_webp,reward_mode,quote_asset,
           mint,status,launch_signature,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
          (ident,wallet,'sol-claim','Banana','BANANA',b'icon','creator','SOL',
           mint,'live','x'*88,int(time.time())))
    with client.session_transaction() as ss:
        ss['wallet']=wallet;ss['csrf_token']='test-csrf'

    tx=Transaction.new_unsigned(Message.new_with_blockhash([
        transfer(TransferParams(from_pubkey=owner.pubkey(),
                 to_pubkey=owner.pubkey(),lamports=0))],
        owner.pubkey(),Hash.default()))
    raw=base64.b64encode(bytes(tx)).decode()
    built=dict(mint=mint,quote_mint=token_launch.WSOL_MINT,
        transaction_b64=raw,transaction_bytes=len(bytes(tx)),
        accrued_raw='14732520',accrued_scope='creator_wallet_all_tokens',
        quote_asset='SOL')
    rpc_calls=[];builder_endpoints=[]
    public='https://api.mainnet-beta.solana.com'

    def rpc(url,*,json,timeout):
        rpc_calls.append((url,json['method']))
        if url in ('https://claim-a.invalid','https://rpc.test.invalid','https://solana-rpc.publicnode.com'):
            return Reply(code=429,error={'code':429})
        if url==public and json['method']=='getLatestBlockhash':
            return Reply({'value':{'blockhash':str(Hash.default())}})
        raise AssertionError((url,json['method']))

    def builder(args,**kwargs):
        assert args[-1].endswith('build-reward-claim.cjs')
        builder_endpoints.append(kwargs['env']['ORCA_LAUNCH_RPC'])
        data=json.loads(kwargs['input'])
        assert data['quote_asset']=='SOL' and data['wallet']==wallet
        return SimpleNamespace(returncode=0,stdout=json_module.dumps(built),stderr='')

    # Avoid shadowing imported json inside builder.
    json_module=json
    with patch.dict(os.environ,{'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'1'}),\
         patch('token_launch.requests.post',side_effect=rpc),\
         patch('token_launch.subprocess.run',side_effect=builder),\
         patch('token_launch.time.sleep'):
        r=client.post('/api/token-launch/'+ident+'/claim/prepare',json={},
                      headers={'X-CSRF-Token':'test-csrf'})
    assert r.status_code==200,r.get_data(as_text=True)
    out=r.get_json()
    assert out['quote_asset']=='SOL' and out['accrued_raw']=='14732520'
    assert builder_endpoints==[public],builder_endpoints
    assert ('https://claim-a.invalid','getLatestBlockhash') in rpc_calls
    assert (public,'getLatestBlockhash') in rpc_calls
    with sqlite3.connect(d.DB_FILE) as c:
        row=c.execute("SELECT status,quote_asset,accrued_raw FROM token_reward_claims").fetchone()
    assert row==('prepared','SOL','14732520'),row
    print('PASS SOL creator claim uses claim RPC fallback for blockhash instead of primary-only RPC')
    print('PASS broad SOL Creator Fee quote starts on working official read-only RPC')
    print('PASS 0.014732520 SOL quote returns unsigned prepared claim only; nothing broadcast')
    tmp.cleanup()

if __name__=='__main__':
    test_sol_creator_claim_uses_claim_rpc_pool()
