"""Opt-in USDC -> native SOL funding before a Phantom-signed Pump launch.

Two explicit wallet approvals: Jupiter's gasless USDC/SOL swap, followed by
the unchanged, rent-bounded creator launch. No platform SOL/key, no auto-buy,
no client-controlled Jupiter request IDs, and no duplicate swap on timeout.
"""
from __future__ import annotations
import base64
import os
import re
import secrets
import sqlite3
import time
from decimal import Decimal
import requests
from flask import jsonify, request
from solders.message import to_bytes_versioned
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

USDC='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
SOL='So11111111111111111111111111111111111111112'
JUP='https://api.jup.ag/swap/v2'
DRAFT=re.compile(r'^[0-9a-f]{32}$')
VALUE=re.compile(r'^(?:[1-9][0-9]{0,2})(?:\.[0-9]{1,6})?$')
SIGNATURE=re.compile(r'^[1-9A-HJ-NP-Za-km-z]{85,90}$')


def install(d):
    app=d.app
    with sqlite3.connect(d.DB_FILE) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS token_launch_funding(
          launch_id TEXT PRIMARY KEY, wallet TEXT NOT NULL, quote_id TEXT NOT NULL,
          request_id TEXT NOT NULL, tx_b64 TEXT NOT NULL,
          amount_raw INTEGER NOT NULL, out_raw INTEGER NOT NULL,
          target_lamports INTEGER NOT NULL, created_at INTEGER NOT NULL,
          status TEXT NOT NULL, signature TEXT NOT NULL DEFAULT '',
          error TEXT NOT NULL DEFAULT '')""")

    def fail(message,status=400):
        return jsonify(ok=False,msg=message),status

    def owner(launch_id):
        wallet=d._authenticated_wallet()
        if not wallet or not d.is_valid_solana_address(wallet):return None,None
        if not DRAFT.fullmatch(launch_id):return wallet,None
        with sqlite3.connect(d.DB_FILE) as db:
            db.row_factory=sqlite3.Row
            row=db.execute('SELECT * FROM token_launches WHERE id=? AND wallet=?',
                           (launch_id,wallet)).fetchone()
        return wallet,dict(row) if row else None

    def stored(launch_id,wallet):
        with sqlite3.connect(d.DB_FILE) as db:
            db.row_factory=sqlite3.Row
            result=db.execute('SELECT * FROM token_launch_funding WHERE launch_id=? AND wallet=?',
                              (launch_id,wallet)).fetchone()
        return dict(result) if result else None

    def rpc(method,params):
        if method not in ('getBalance','getSignatureStatuses'):raise ValueError('Forbidden RPC method')
        endpoints=[]
        for endpoint in (getattr(d,'SOLANA_RPC_URL',''), 'https://solana-rpc.publicnode.com',
                         'https://api.mainnet-beta.solana.com'):
            if endpoint and endpoint not in endpoints:endpoints.append(endpoint)
        for endpoint in endpoints:
            try:
                response=requests.post(endpoint,json={'jsonrpc':'2.0','id':1,
                    'method':method,'params':params},timeout=7)
                if response.status_code in (429,500,502,503,504):continue
                response.raise_for_status()
                data=response.json()
                if not isinstance(data,dict) or data.get('error'):continue
                return data.get('result')
            except (requests.RequestException,ValueError):
                continue
        raise RuntimeError('Solana balance/confirmation is unavailable. Check the existing transaction later.')

    def balance(wallet):
        value=(rpc('getBalance',[wallet,{'commitment':'confirmed'}]) or {}).get('value')
        if type(value) is not int or value<0:raise RuntimeError('Cannot verify wallet SOL balance')
        return value

    def target(row):
        pilot=(os.getenv('ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED','0')!='1' and
               os.getenv('ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_ENABLED','0')=='1' and
               row['wallet'] in set(os.getenv('ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_WALLETS','').split(',')))
        return 30_000_000 if pilot else (115_000_000 if row['reward_mode']=='community' else 60_000_000)

    def enabled(row):
        return row['status'] in ('draft','prepared') and (
            os.getenv('ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED','0')=='1' or (
            os.getenv('ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_ENABLED','0')=='1' and
            row['wallet'] in set(os.getenv('ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_WALLETS','').split(','))))

    def public_state(row,have=None):
        return {'status':row['status'],'quote_id':row['quote_id'],
           'signature':row['signature'],'amount_usdc':f"{row['amount_raw']/1e6:.6f}",
           'expected_sol':f"{row['out_raw']/1e9:.9f}",
           'target_sol':f"{row['target_lamports']/1e9:.9f}",
           'expires_in':max(0,row['created_at']+110-int(time.time())),
           'balance_sol':f"{have/1e9:.9f}" if have is not None else None}

    @app.post('/api/token-launch/<launch_id>/fund/quote')
    @d.rate_limit(4,60)
    def quote_funding(launch_id):
        wallet,row=owner(launch_id)
        if not wallet:return fail('Connect Phantom',401)
        if not row:return fail('Your saved launch was not found',404)
        if not d._validate_csrf(request.headers.get('X-CSRF-Token','')):return fail('CSRF validation failed',403)
        if not enabled(row):return fail('Funding is only available before approving your own launch',409)
        api_key=os.getenv('JUPITER_API_KEY','').strip()
        if not api_key:return fail('USDC launch funding is not configured yet',503)
        body=request.get_json(silent=True)
        auto=isinstance(body,dict) and 'max_usdc' in body
        value=body.get('max_usdc' if auto else 'amount_usdc') if isinstance(body,dict) else None
        if not isinstance(value,str) or not VALUE.fullmatch(value):
            return fail('Enter a USDC amount between 5 and 250 (up to 6 decimals)')
        amount=int(Decimal(value)*1_000_000)
        if not 5_000_000<=amount<=250_000_000:
            return fail('Enter a USDC amount between 5 and 250')
        current=stored(launch_id,wallet); now=int(time.time())
        try:have=balance(wallet)
        except RuntimeError as exc:return fail(str(exc),503)
        goal=target(row)
        if have>=goal:
            return fail('Wallet already has the SOL launch reserve. Approve the saved launch in Phantom.',409)
        if current:
            if current['status']=='submitted':
                return fail('An earlier USDC funding transaction may still settle. Check its status before swapping again.',409)
            if current['status']=='confirmed' and current['created_at']+120>now:
                return fail('The previous USDC swap succeeded. Wait for the SOL balance to update before paying again.',409)
            if current['status']=='prepared' and current['created_at']+110>now:
                if auto and current['amount_raw']>amount:
                    return fail('Existing quote exceeds your new USDC limit. Let it expire before requoting.',409)
                return jsonify(ok=True,reused=True,transaction_b64=current['tx_b64'],
                               **public_state(current,have))
        try:
            if auto:
                # Price-only Jupiter quote: NO taker, transaction, signature or spend.
                indicative=requests.get(JUP+'/order',params={'inputMint':USDC,
                      'outputMint':SOL,'amount':'10000000'},
                      headers={'x-api-key':api_key,'Accept':'application/json'},timeout=12)
                indicative.raise_for_status()
                price=indicative.json()
                out_ten=price.get('outAmount') if isinstance(price,dict) else None
                if not isinstance(out_ten,str) or not out_ten.isdecimal() or int(out_ten)<=0:
                    return fail('Could not calculate the live SOL reserve price. No USDC was spent.',503)
                # 10% reserve for price movement, 15% extra quote margin.
                desired=goal-have
                estimated=(desired*10_000_000*115+int(out_ten)*90-1)//(int(out_ten)*90)
                amount=max(12_000_000,estimated)
                if amount>int(Decimal(value)*1_000_000):
                    return fail('The current SOL launch reserve needs more USDC than your limit. Increase the maximum; nothing was sent.',409)
            reply=requests.get(JUP+'/order',params={'inputMint':USDC,'outputMint':SOL,
                    'amount':str(amount),'taker':wallet},
                    headers={'x-api-key':api_key,'Accept':'application/json'},timeout=18)
            if reply.status_code==429:return fail('Jupiter is busy; retry the SAME launch later',503)
            reply.raise_for_status()
            order=reply.json()
            if not isinstance(order,dict):raise ValueError('Bad Jupiter response')
            if not order.get('transaction'):
                if order.get('errorCode')==1:
                    return fail('Not enough USDC for this swap in your Phantom wallet. Nothing was spent.',409)
                if order.get('errorCode')==3:
                    return fail('This USDC amount is below the current Jupiter gasless minimum. Increase it; nothing was sent.',409)
                return fail('Jupiter could not prepare a gasless USDC swap. No transaction was sent.',503)
            raw=order.get('transaction'); request_id=order.get('requestId')
            out=order.get('outAmount')
            if (not isinstance(raw,str) or not raw or len(raw)>10000 or
                not isinstance(request_id,str) or not 5<=len(request_id)<=160 or
                not isinstance(out,str) or not out.isdecimal() or
                not order.get('gasless') or order.get('signatureFeePayer')==wallet or
                str(order.get('inAmount'))!=str(amount)):
                return fail('Jupiter did not offer a verified gasless USDC-to-SOL route. No swap was sent.',503)
            output=int(out)
            if output<=0 or output*90//100 < goal-have:
                return fail('This USDC amount cannot cover the SOL launch reserve after slippage. Increase the USDC amount. Nothing was spent.',409)
            unsigned=VersionedTransaction.from_bytes(base64.b64decode(raw,validate=True))
            keys=list(unsigned.message.account_keys)
            required=int(unsigned.message.header.num_required_signatures)
            if (Pubkey.from_string(wallet) not in keys[:required] or
                    str(keys[0])!=str(order.get('signatureFeePayer')) or
                    keys[0]==Pubkey.from_string(wallet)):
                return fail('Jupiter transaction is not safely gasless for this wallet',503)
        except (requests.RequestException,ValueError,TypeError,KeyError) as exc:
            return fail('A safe gasless USDC quote is unavailable. No transaction was sent.',503)
        except RuntimeError as exc:return fail(str(exc),503)
        quoted={'launch_id':launch_id,'wallet':wallet,'quote_id':secrets.token_hex(16),
              'request_id':request_id,'tx_b64':raw,'amount_raw':amount,'out_raw':output,
              'target_lamports':goal,'created_at':now,'status':'prepared','signature':''}
        with sqlite3.connect(d.DB_FILE,timeout=8) as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT status,created_at FROM token_launch_funding WHERE launch_id=? AND wallet=?',
                                (launch_id,wallet)).fetchone()
            if previous and (previous[0]=='submitted' or (previous[0]=='prepared' and previous[1]+110>now)):
                return fail('Funding quote changed in another tab. Reload and check it before approving.',409)
            db.execute("""INSERT INTO token_launch_funding(
                  launch_id,wallet,quote_id,request_id,tx_b64,amount_raw,out_raw,target_lamports,
                  created_at,status,signature) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(launch_id) DO UPDATE SET
                  quote_id=excluded.quote_id,request_id=excluded.request_id,
                  tx_b64=excluded.tx_b64,amount_raw=excluded.amount_raw,
                  out_raw=excluded.out_raw,target_lamports=excluded.target_lamports,
                  created_at=excluded.created_at,status='prepared',signature='',error=''""",
                  tuple(quoted[k] for k in ('launch_id','wallet','quote_id','request_id','tx_b64',
                      'amount_raw','out_raw','target_lamports','created_at','status','signature')))
        return jsonify(ok=True,transaction_b64=raw,**public_state(quoted,have))

    @app.post('/api/token-launch/<launch_id>/fund/execute')
    @d.rate_limit(4,60)
    def execute_funding(launch_id):
        wallet,launch=owner(launch_id)
        if not wallet:return fail('Connect Phantom',401)
        if not launch:return fail('Launch not found',404)
        if not d._validate_csrf(request.headers.get('X-CSRF-Token','')):return fail('CSRF validation failed',403)
        body=request.get_json(silent=True) or {}
        quote_id=body.get('quote_id'); b64=body.get('signed_transaction_b64')
        if (not isinstance(quote_id,str) or not DRAFT.fullmatch(quote_id)
            or not isinstance(b64,str) or len(b64)>12000):
            return fail('Invalid wallet approval')
        row=stored(launch_id,wallet)
        if not row or row['quote_id']!=quote_id:return fail('Quote not found; check existing funding',409)
        if row['status']!='prepared' or row['created_at']+110<int(time.time()):
            return fail('This quote is already submitted or expired; check funding status',409)
        try:
            signed=VersionedTransaction.from_bytes(base64.b64decode(b64,validate=True))
            original=VersionedTransaction.from_bytes(base64.b64decode(row['tx_b64'],validate=True))
            msg=to_bytes_versioned(original.message)
            if to_bytes_versioned(signed.message)!=msg:raise ValueError
            signers=list(original.message.account_keys)[:original.message.header.num_required_signatures]
            user=signers.index(Pubkey.from_string(wallet))
            if len(signed.signatures)!=len(original.signatures):raise ValueError
            if not signed.signatures[user].verify(Pubkey.from_string(wallet),msg):raise ValueError
            if any(x!=y for index,(x,y) in enumerate(zip(signed.signatures,original.signatures)) if index!=user):
                raise ValueError
        except (ValueError,IndexError,TypeError,AttributeError):
            return fail('Signed transaction does not match the original USDC quote',400)
        with sqlite3.connect(d.DB_FILE,timeout=8) as db:
            changed=db.execute("""UPDATE token_launch_funding SET status='submitted'
                       WHERE launch_id=? AND wallet=? AND quote_id=? AND status='prepared'""",
                       (launch_id,wallet,quote_id))
            if changed.rowcount!=1:return fail('This funding order is already being processed; check status',409)
        # A timeout has UNKNOWN settlement; do not automatically re-broadcast.
        try:
            result=requests.post(JUP+'/execute',
               json={'signedTransaction':b64,'requestId':row['request_id']},
               headers={'x-api-key':os.environ['JUPITER_API_KEY'],
                        'Content-Type':'application/json'},timeout=38)
            result.raise_for_status()
            data=result.json()
            sig=data.get('signature','')
            state='confirmed' if data.get('status')=='Success' and isinstance(sig,str) and SIGNATURE.fullmatch(sig) else 'submitted'
            with sqlite3.connect(d.DB_FILE) as db:
                db.execute("""UPDATE token_launch_funding SET status=?,signature=?
                       WHERE launch_id=? AND wallet=? AND quote_id=? AND status='submitted'""",
                       (state,sig if isinstance(sig,str) and SIGNATURE.fullmatch(sig) else '',
                        launch_id,wallet,quote_id))
            return jsonify(ok=True,status=state,signature=sig if isinstance(sig,str) and SIGNATURE.fullmatch(sig) else '',
                message='Check SOL balance before approving the launch. Never reapprove an uncertain swap.')
        except (requests.RequestException,ValueError,KeyError):
            return jsonify(ok=True,status='submitted',signature='',
                message='Jupiter confirmation is unknown. Do not approve another USDC swap. Check wallet balance and funding status.'),202

    @app.get('/api/token-launch/<launch_id>/fund/status')
    @d.rate_limit(12,60)
    def funding_status(launch_id):
        wallet,launch=owner(launch_id)
        if not wallet:return fail('Connect Phantom',401)
        if not launch:return fail('Launch not found',404)
        row=stored(launch_id,wallet)
        try:have=balance(wallet)
        except RuntimeError as exc:return fail(str(exc),503)
        goal=target(launch)
        result={'ok':True,'balance_sol':f"{have/1e9:.9f}",
                'target_sol':f"{goal/1e9:.9f}",'ready':have>=goal,
                'funding':public_state(row,have) if row else None}
        return jsonify(result)
