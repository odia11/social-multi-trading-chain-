"""Relay only already-Phantom-signed Solana transactions. No wallet signing.

Failover is limited to the IDENTICAL bytes and signature. Sending twice to
independent RPCs cannot create a second token (same Solana transaction id).
"""
import base64
import requests

def relay_identical_signed(signed_bytes, expected_signature, endpoints, *, timeout=9):
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
    for endpoint in endpoints:
        if not endpoint or endpoint in seen:continue
        seen.add(endpoint)
        try:
            response=requests.post(endpoint,json=request,timeout=timeout)
            if response.status_code in (429,500,502,503,504):continue
            response.raise_for_status()
            value=response.json()
            if not isinstance(value,dict):continue
            if value.get('result')==expected_signature:return True
            error=value.get('error') or {}
            if isinstance(error,dict) and error.get('code') in (429,-32005):
                continue
            # Could be an expired blockhash or deterministic simulation error.
            # Another RPC may be better synced, but never bypass preflight.
        except (requests.RequestException,ValueError,TypeError):
            continue
    return False
