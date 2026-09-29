"""Read-only, fail-closed recovery proof for a Phantom-signed token launch.

Only after Solana finality shows the old blockhash expired, neither the
signature nor mint nor Pump bonding curve exists on multiple RPCs can
OrcAgent offer a NEW wallet approval on the SAME saved draft.
"""
import base64
import requests
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import Transaction

PUBLIC_RPCS=('https://solana-rpc.publicnode.com',
             'https://api.mainnet-beta.solana.com')

def _read_rpc(url,method,params):
    response=requests.post(url,json={'jsonrpc':'2.0','id':1,
                              'method':method,'params':params},timeout=8)
    response.raise_for_status()
    reply=response.json()
    if not isinstance(reply,dict) or reply.get('error') or 'result' not in reply:
        raise ValueError('RPC unavailable')
    return reply['result']

def prove_expired_unlanded(row,*,primary='',providers=None):
    """Return (safe_to_reprepare, status), without modifying or sending.

    Require two *distinct* independent mainnet providers for absence proofs.
    On error, absence of a reply must never be treated as an empty account.
    """
    sig=row.get('launch_signature')
    raw=row.get('prepare_tx_b64')
    mint=row.get('mint')
    if not sig or not raw or not mint or row.get('status')!='submitted':
        return False,'No submitted launch for recovery'
    old=Transaction.from_bytes(base64.b64decode(raw,validate=True))
    message=bytes(old.message)
    if (str(old.message.account_keys[0])!=row['wallet']
        or not Signature.from_string(sig).verify(old.message.account_keys[0],message)
        or any(not signature.verify(old.message.account_keys[index],message)
               for index,signature in enumerate(old.signatures) if index>0)
        or str(Pubkey.from_string(mint)) not in
             [str(key) for key in old.message.account_keys]):
        return False,'Stored launch signature cannot be verified'
    curve,_=Pubkey.find_program_address(
        [b'bonding-curve',bytes(Pubkey.from_string(mint))],
         Pubkey.from_string('6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P'))
    providers=providers or (primary,)+PUBLIC_RPCS
    valid_sources=set()
    errors=0
    for url in providers:
        if not url or url in valid_sources:continue
        try:
            st=_read_rpc(url,'getSignatureStatuses',[[sig],{'searchTransactionHistory':True}])
            status=(st or {}).get('value')
            if not isinstance(status,list) or len(status)!=1:
                raise ValueError('Malformed signature lookup')
            if status[0] is not None:
                return False,'The original transaction exists on Solana; check its result'
            block=_read_rpc(url,'isBlockhashValid',[
                str(old.message.recent_blockhash),{'commitment':'finalized'}])
            if not isinstance(block,dict) or not isinstance(block.get('value'),bool):
                raise ValueError('Malformed blockhash lookup')
            if block['value']:
                return False,'The signed transaction is still valid. Do not create another token.'
            for address in (mint,str(curve)):
                account=_read_rpc(url,'getAccountInfo',[address,
                    {'encoding':'base64','commitment':'finalized'}])
                if not isinstance(account,dict) or 'value' not in account:
                    raise ValueError('Malformed account lookup')
                if account['value'] is not None:
                    return False,'The original token already exists on Solana'
            valid_sources.add(url)
        except (requests.RequestException,ValueError,KeyError,TypeError):
            errors+=1
    if len(valid_sources)<2:
        return False,'Solana recovery checks unavailable on two independent RPCs. Wait and check the original signature.'
    return True,'Original signature absent, old blockhash finalized as expired and mint absent on two RPCs'
