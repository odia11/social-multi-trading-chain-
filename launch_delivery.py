"""Relay only already-Phantom-signed Solana transactions. No wallet signing.

Failover is limited to the IDENTICAL bytes and signature. Sending twice to
independent RPCs cannot create a second token (same Solana transaction id).
"""
import base64
import requests

def relay_identical_signed(signed_bytes, expected_signature, endpoints, *, timeout=9, reasons=None):
    from solders.transaction import Transaction
    raw=bytes(signed_bytes)
    tx=Transaction.from_bytes(raw)
    if (str(tx.signatures[0])!=expected_signature or not all(tx.verify_with_results())
            or not 1<=len(raw)<=1232):
        raise ValueError('Invalid original Phantom-signed transaction')
    request={'jsonrpc':'2.0','id':1,'method':'sendTransaction',
             'params':[base64.b64encode(raw).decode(),
              {'encoding':'base64','skipPreflight':False,
               'preflightCommitment':'confirmed','maxRetries':2}]}
    seen=set()
    if reasons is None:reasons=[]
    for endpoint in endpoints:
        if not endpoint or endpoint in seen:continue
        seen.add(endpoint)
        try:
            response=requests.post(endpoint,json=request,timeout=timeout)
            if response.status_code in (429,500,502,503,504):
                reasons.append('RPC temporarily unavailable')
                continue
            response.raise_for_status()
            value=response.json()
            if not isinstance(value,dict):continue
            if value.get('result')==expected_signature:return True
            error=value.get('error') or {}
            if isinstance(error,dict):
                message=str(error.get('message') or '').lower()
                logs=((error.get('data') or {}).get('logs') or []) if isinstance(error.get('data'),dict) else []
                joined=' '.join(str(x).lower() for x in logs[-8:])+' '+message
                if 'blockhash not found' in joined:reasons.append('The signing window expired before RPC delivery')
                elif 'insufficient funds' in joined:reasons.append('Insufficient SOL for network rent or fees')
                elif 'already processed' in joined:return True
                elif 'simulation failed' in joined:reasons.append('Solana simulation rejected this transaction')
                else:reasons.append('RPC rejected the transaction')
            # Another RPC may be better synced, but never bypass preflight.
        except (requests.RequestException,ValueError,TypeError):
            reasons.append('RPC temporarily unavailable')
            continue
    return False
