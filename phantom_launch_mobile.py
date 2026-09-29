"""Phantom mobile-browser token launch signing without an injected provider.

Two-step Phantom connect (once per wallet) / signTransaction links.
The server relays ONLY already-signed transactions with identical bytes
after owner signature validation. No server wallet signs.
Sessions and short-lived action keys are encrypted at rest with ENCRYPTION_KEY.
"""
import base64
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from urllib.parse import urlencode
import requests
from cryptography.fernet import Fernet
from flask import jsonify, request, render_template, make_response
from nacl.public import Box, PrivateKey, PublicKey
from solders.pubkey import Pubkey
from solders.transaction import Transaction
from solders.signature import Signature

ALPHABET='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
MAP={c:i for i,c in enumerate(ALPHABET)}
TOKEN=re.compile(r'^[0-9a-f]{64}$')
SIG=re.compile(r'^[1-9A-HJ-NP-Za-km-z]{85,90}$')
BASE='https://orcagent.fun'
TTL=600

def b58enc(buf):
    value=int.from_bytes(buf,'big')
    encoded=''
    while value:
        value,rem=divmod(value,58)
        encoded=ALPHABET[rem]+encoded
    return '1'*(len(buf)-len(buf.lstrip(b'\x00')))+encoded

def b58dec(value):
    if not isinstance(value,str) or len(value)>12000:raise ValueError('Invalid base58 value')
    number=0
    for c in value:number=number*58+MAP[c]
    zeros=len(value)-len(value.lstrip('1'))
    return b'\0'*zeros+number.to_bytes((number.bit_length()+7)//8,'big')

def install(d,lookup,check_signature,mint_exists,sharing_check,blockhash_valid=None,claim_wrapper_ok=None):
    app=d.app
    fernet=Fernet(os.environ['ENCRYPTION_KEY'].encode())
    with sqlite3.connect(d.DB_FILE) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS phantom_launch_links(
          token TEXT PRIMARY KEY, launch_id TEXT NOT NULL, wallet TEXT NOT NULL,
          stage TEXT NOT NULL, digest TEXT NOT NULL, secret BLOB NOT NULL,
          created_at INTEGER NOT NULL, status TEXT NOT NULL,
          signature TEXT NOT NULL DEFAULT '')""")
        columns={r[1] for r in db.execute('PRAGMA table_info(phantom_launch_links)')}
        if 'return_to_pwa' not in columns:
            db.execute('ALTER TABLE phantom_launch_links ADD COLUMN return_to_pwa INTEGER NOT NULL DEFAULT 0')
        if 'signed_tx' not in columns:
            db.execute('ALTER TABLE phantom_launch_links ADD COLUMN signed_tx BLOB')
        if 'claim_id' not in columns:
            db.execute("ALTER TABLE phantom_launch_links ADD COLUMN claim_id TEXT NOT NULL DEFAULT ''")
        db.execute("""CREATE TABLE IF NOT EXISTS phantom_launch_sessions(
          wallet TEXT PRIMARY KEY, secret BLOB NOT NULL, saved_at INTEGER NOT NULL)""")

    def fail(reason,code=400):return jsonify(ok=False,msg=reason),code

    def load(token):
        if not isinstance(token,str) or not TOKEN.fullmatch(token):return None
        with sqlite3.connect(d.DB_FILE) as db:
            db.row_factory=sqlite3.Row
            found=db.execute('SELECT * FROM phantom_launch_links WHERE token=?',(token,)).fetchone()
        return dict(found) if found else None

    def claim_for(flow):
        if flow['stage']!='claim' or not flow.get('claim_id'):return None
        with sqlite3.connect(d.DB_FILE) as db:
            db.row_factory=sqlite3.Row
            claim=db.execute('''SELECT * FROM token_reward_claims
                WHERE id=? AND launch_id=? AND wallet=?''',
                (flow['claim_id'],flow['launch_id'],flow['wallet'])).fetchone()
        return dict(claim) if claim else None

    # A Solana blockhash stays valid for ~60-90 seconds. One fetched moments
    # ago can still look invalid to a slightly lagging RPC node that has not
    # seen it yet -- which refused a freshly prepared claim ("Claim approval
    # expired") before Phantom was even opened. Within this window after the
    # transaction was prepared it cannot have expired, so the RPC is not asked.
    BLOCKHASH_MIN_LIFE=45

    def still_valid(raw,issued_at,claim_read=False):
        if issued_at and 0<=int(time.time())-int(issued_at)<BLOCKHASH_MIN_LIFE:
            return True
        return blockhash_valid(raw,claim_read=True) if claim_read else blockhash_valid(raw)

    def current(flow):
        row=lookup(flow['launch_id'],flow['wallet'])
        if not row:return None,None
        if flow['stage']=='claim':
            claim=claim_for(flow)
            raw=claim['transaction_b64'] if claim and claim['status']=='prepared' and not claim['signature'] else None
            return row,(raw if raw and hashlib.sha256(raw.encode()).hexdigest()==flow['digest'] else None)
        field='prepare_tx_b64' if flow['stage']=='create' else 'finalize_tx_b64'
        raw=row[field]
        if not raw or hashlib.sha256(raw.encode()).hexdigest()!=flow['digest']:
            return row,None
        permitted=('prepared',) if flow['stage']=='create' else ('finalize_prepared',)
        if row['status'] not in permitted:return row,None
        return row,raw

    def encode(payload,sk,pk):
        encrypted=Box(PrivateKey(sk),PublicKey(b58dec(pk))).encrypt(
            json.dumps(payload,separators=(',',':')).encode())
        return b58enc(encrypted.nonce),b58enc(encrypted.ciphertext)

    def decrypt(sk,pk,nonce,data):
        msg=Box(PrivateKey(sk),PublicKey(b58dec(pk))).decrypt(
            b58dec(data),b58dec(nonce))
        result=json.loads(msg)
        if not isinstance(result,dict):raise ValueError('Invalid Phantom reply')
        return result

    def redirect_link(flow,step):
        return BASE+'/phantom-launch-callback?'+urlencode({
            'token':flow['token'],'step':step,
            'pwa':'1' if flow.get('return_to_pwa') else '0',
            'action':'claim' if flow['stage']=='claim' else 'launch'})

    def connect_url(flow):
        sk=fernet.decrypt(flow['secret'])
        return BASE.replace('orcagent.fun','phantom.app')+'/ul/v1/connect?'+urlencode({
            'app_url':BASE,'cluster':'mainnet-beta',
            'dapp_encryption_public_key':b58enc(bytes(PrivateKey(sk).public_key)),
            'redirect_link':redirect_link(flow,'connect')})

    def sign_url(flow,sk,phantom_pk,session):
        row,raw=current(flow)
        if raw is None:raise ValueError('Launch approval expired or changed. Open the saved launch again.')
        transaction=b58enc(base64.b64decode(raw,validate=True))
        # Phantom mobile rejects signAndSendTransaction with -32601 on iOS.
        # Sign only; the callback verifies the exact transaction and relays its
        # identical signed bytes with preflight and RPC failover.
        nonce,payload=encode({'transaction':transaction,'session':session},sk,phantom_pk)
        return 'https://phantom.app/ul/v1/signTransaction?'+urlencode({
            'dapp_encryption_public_key':b58enc(bytes(PrivateKey(sk).public_key)),
            'nonce':nonce,'redirect_link':redirect_link(flow,'sign'),
            'payload':payload})

    def session_for(wallet):
        with sqlite3.connect(d.DB_FILE) as db:
            result=db.execute('SELECT secret FROM phantom_launch_sessions WHERE wallet=?',
                              (wallet,)).fetchone()
        if not result:return None
        try:
            record=json.loads(fernet.decrypt(result[0]))
            return (b58dec(record['sk']),record['pk'],record['session'])
        except (ValueError,KeyError,TypeError):return None

    @app.post('/api/token-launch/<launch_id>/phantom/start')
    @d.rate_limit(4,60)
    def phantom_launch_start(launch_id):
        wallet=d._authenticated_wallet()
        if not wallet:return fail('Connect your wallet',401)
        if not d._validate_csrf(request.headers.get('X-CSRF-Token','')):
            return fail('CSRF validation failed',403)
        row=lookup(launch_id,wallet)
        if not row:return fail('Launch not found',404)
        body=request.get_json(silent=True) or {}
        stage=body.get('stage')
        if stage not in ('create','finalize'):return fail('Invalid launch stage')
        field='prepare_tx_b64' if stage=='create' else 'finalize_tx_b64'
        valid_status='prepared' if stage=='create' else 'finalize_prepared'
        if row['status']!=valid_status or not row[field]:
            return fail('Prepare your saved token launch before requesting Phantom',409)
        # Never resume a different action from an already-submitted launch.
        nonce=secrets.token_hex(32)
        sk=bytes(PrivateKey.generate())
        cached=session_for(wallet)
        if cached:
            sk,pk,session=cached
        flow={'token':nonce,'launch_id':launch_id,'wallet':wallet,'stage':stage,
              'digest':hashlib.sha256(row[field].encode()).hexdigest(),
              'secret':fernet.encrypt(sk),'created_at':int(time.time()),
              'status':'sign' if cached else 'connect',
              'return_to_pwa':int(body.get('return_to_pwa') is True)}
        with sqlite3.connect(d.DB_FILE,timeout=8) as db:
            db.execute('DELETE FROM phantom_launch_links WHERE created_at<?',
                       (int(time.time())-TTL,))
            db.execute("""INSERT INTO phantom_launch_links
              (token,launch_id,wallet,stage,digest,secret,created_at,status,return_to_pwa)
              VALUES (:token,:launch_id,:wallet,:stage,:digest,:secret,:created_at,:status,:return_to_pwa)""",
              flow)
        if cached:
            try:url=sign_url(flow,sk,pk,session)
            except (ValueError,KeyError):
                return fail('Prepared launch expired. Use the saved launch to try again.',409)
        else:url=connect_url(flow)
        return jsonify(ok=True,url=url,requires_connect=not bool(cached))

    @app.post('/api/token-launch/<launch_id>/claim/phantom/start')
    @d.rate_limit(4,60)
    def phantom_claim_start(launch_id):
        wallet=d._authenticated_wallet()
        if not wallet:return fail('Connect your wallet',401)
        if not d._validate_csrf(request.headers.get('X-CSRF-Token','')):
            return fail('CSRF validation failed',403)
        row=lookup(launch_id,wallet)
        if not row or row['status']!='live':return fail('Confirmed launch not found',404)
        body=request.get_json(silent=True) or {}
        claim_id=body.get('claim_id')
        if not isinstance(claim_id,str) or not re.fullmatch(r'[0-9a-f]{32}',claim_id):
            return fail('Invalid claim ID')
        with sqlite3.connect(d.DB_FILE) as db:
            db.row_factory=sqlite3.Row
            claim=db.execute('''SELECT * FROM token_reward_claims WHERE id=?
                AND launch_id=? AND wallet=?''',(claim_id,launch_id,wallet)).fetchone()
        if not claim or claim['status']!='prepared' or claim['signature']:
            return fail('This claim was already submitted. Check claim history.',409)
        raw=claim['transaction_b64']
        try:
            valid=bool(raw and still_valid(raw,claim['created_at'],claim_read=True))
        except RuntimeError:
            return fail('Solana is unavailable. No claim transaction was sent. Retry shortly.',503)
        if not valid:
            return fail('Claim approval expired. Check claim history before preparing another claim.',409)
        sk=bytes(PrivateKey.generate());cached=session_for(wallet)
        if cached:sk,pk,session=cached
        flow={'token':secrets.token_hex(32),'launch_id':launch_id,'wallet':wallet,
              'stage':'claim','claim_id':claim_id,
              'digest':hashlib.sha256(raw.encode()).hexdigest(),
              'secret':fernet.encrypt(sk),'created_at':int(time.time()),
              'status':'sign' if cached else 'connect',
              'return_to_pwa':int(body.get('return_to_pwa') is True)}
        with sqlite3.connect(d.DB_FILE,timeout=8) as db:
            db.execute('DELETE FROM phantom_launch_links WHERE created_at<?',(int(time.time())-TTL,))
            db.execute('''INSERT INTO phantom_launch_links
                (token,launch_id,wallet,stage,claim_id,digest,secret,created_at,status,return_to_pwa)
                VALUES (:token,:launch_id,:wallet,:stage,:claim_id,:digest,:secret,:created_at,:status,:return_to_pwa)''',flow)
        url=sign_url(flow,sk,pk,session) if cached else connect_url(flow)
        return jsonify(ok=True,url=url,requires_connect=not bool(cached))

    @app.post('/api/token-launch/<launch_id>/claim/phantom/retry-delivery')
    @d.rate_limit(4,60)
    def phantom_claim_retry_delivery(launch_id):
        wallet=d._authenticated_wallet()
        if not wallet:return fail('Connect your wallet',401)
        if not d._validate_csrf(request.headers.get('X-CSRF-Token','')):
            return fail('CSRF validation failed',403)
        body=request.get_json(silent=True) or {}
        claim_id=body.get('claim_id')
        if not isinstance(claim_id,str) or not re.fullmatch(r'[0-9a-f]{32}',claim_id):
            return fail('Invalid claim ID')
        with sqlite3.connect(d.DB_FILE) as db:
            db.row_factory=sqlite3.Row
            claim=db.execute('''SELECT * FROM token_reward_claims WHERE id=? AND launch_id=?
                AND wallet=? AND status='submitted' ''',(claim_id,launch_id,wallet)).fetchone()
            link=db.execute('''SELECT * FROM phantom_launch_links WHERE claim_id=?
                AND launch_id=? AND wallet=? AND status='submitted' AND signed_tx IS NOT NULL
                ORDER BY created_at DESC LIMIT 1''',(claim_id,launch_id,wallet)).fetchone()
        if not claim or not link or claim['signature']!=link['signature']:
            return fail('No matching signed claim is pending. Check claim history.',409)
        try:
            raw=fernet.decrypt(link['signed_tx'])
            signed=Transaction.from_bytes(raw)
            original=Transaction.from_bytes(base64.b64decode(claim['transaction_b64'],validate=True))
            same=bytes(signed.message)==bytes(original.message)
            wrapped=(not same and claim_wrapper_ok is not None
                     and claim_wrapper_ok(signed.message,original.message,wallet))
            if (not (same or wrapped)
                    or str(signed.signatures[0])!=claim['signature']
                    or not all(signed.verify_with_results())):
                return fail('Saved claim signature does not match',409)
            if check_signature(claim['signature'],{'prepare_tx_b64':claim['transaction_b64'],
                    'wallet':wallet,'mint':claim['mint']},'claim'):
                return jsonify(ok=True,confirmed=True,signature=claim['signature'])
            if not still_valid(claim['transaction_b64'],claim['created_at'],claim_read=True):
                return fail('The original claim expired. Check history before preparing another claim.',409)
            from launch_delivery import relay_identical_signed
            delivered=relay_identical_signed(raw,claim['signature'],[
                os.getenv('ORCA_LAUNCH_RPC',''),
                getattr(d,'SOLANA_RPC_URL','') or getattr(d,'SOLANA_RPC',''),
                'https://solana-rpc.publicnode.com',
                'https://api.mainnet-beta.solana.com'])
            return jsonify(ok=True,delivered=bool(delivered),signature=claim['signature'])
        except (RuntimeError,ValueError,TypeError,KeyError):
            return fail('Original claim cannot be checked right now. Do not approve another claim.',503)

    @app.post('/api/token-launch/<launch_id>/phantom/retry-delivery')
    @d.rate_limit(4,60)
    def phantom_retry_delivery(launch_id):
        wallet=d._authenticated_wallet()
        if not wallet:return fail('Connect your wallet',401)
        if not d._validate_csrf(request.headers.get('X-CSRF-Token','')):
            return fail('CSRF validation failed',403)
        row=lookup(launch_id,wallet)
        if not row:return fail('Launch not found',404)
        with sqlite3.connect(d.DB_FILE) as db:
            db.row_factory=sqlite3.Row
            link=db.execute("""SELECT * FROM phantom_launch_links
                WHERE launch_id=? AND wallet=? AND status='submitted'
                AND signed_tx IS NOT NULL ORDER BY created_at DESC LIMIT 1""",
                (launch_id,wallet)).fetchone()
        if not link:return fail('No signed transaction is saved for delivery. Check the original transaction first.',409)
        stage=link['stage']
        field='launch_signature' if stage=='create' else 'finalize_signature'
        prepared='prepare_tx_b64' if stage=='create' else 'finalize_tx_b64'
        expected='submitted' if stage=='create' else 'finalize_submitted'
        if row['status']!=expected or row[field]!=link['signature']:
            return fail('Launch status changed. Check the original transaction.',409)
        try:
            raw=fernet.decrypt(link['signed_tx'])
            signed=Transaction.from_bytes(raw)
            original=Transaction.from_bytes(base64.b64decode(row[prepared],validate=True))
            if (str(signed.signatures[0])!=link['signature'] or
                    bytes(signed.message)!=bytes(original.message) or
                    not all(signed.verify_with_results())):
                return fail('Saved signature does not match this launch',409)
            try:
                confirmed=check_signature(link['signature'],row,stage)
            except ValueError:
                return fail('The original transaction failed on Solana. Check its signature before taking any new action.',409)
            except RuntimeError:
                confirmed=False
            if confirmed:
                return jsonify(ok=True,confirmed=True,signature=link['signature'])
            if blockhash_valid is not None and not blockhash_valid(row[prepared]):
                return fail('Original blockhash expired. Use Recover expired launch on the saved token; do not create a second token.',409)
            from launch_delivery import relay_identical_signed
            reasons=[]
            sent=relay_identical_signed(raw,link['signature'],[
                os.getenv('ORCA_LAUNCH_RPC',''),
                getattr(d,'SOLANA_RPC_URL','') or getattr(d,'SOLANA_RPC',''),
                'https://solana-rpc.publicnode.com',
                'https://api.mainnet-beta.solana.com'],reasons=reasons)
            reason=next((x for x in reasons if x not in
                ('RPC temporarily unavailable','RPC rejected the transaction')),
                'RPC delivery could not be verified')
            return jsonify(ok=True,submitted=True,delivered=bool(sent),
                signature=link['signature'],
                msg='Original signed transaction resent.' if sent else reason)
        except (RuntimeError,ValueError,TypeError,KeyError):
            return fail('Saved transaction cannot be checked. Do not create another token.',503)

    @app.get('/phantom-launch-callback')
    def phantom_launch_callback():
        response=make_response(render_template('phantom_launch_callback.html'))
        response.headers['Cache-Control']='no-store'
        response.headers['Referrer-Policy']='no-referrer'
        return response

    @app.post('/api/phantom-launch/complete')
    @d.rate_limit(12,60)
    @d.csrf_exempt
    def phantom_launch_complete():
        data=request.get_json(silent=True) or {}
        flow=load(data.get('token'))
        if not flow or time.time()-flow['created_at']>TTL:
            return fail('Phantom approval expired. Open the original saved launch again.',410)
        if data.get('errorCode'):
            # A cached Phantom session can expire/revoke while OrcAgent's login
            # remains valid. Drop only the action-session cache so the SAME
            # saved launch reconnects cleanly on the next tap instead of
            # trapping the user in a permanent failed-sign loop.
            if data.get('step')=='sign':
                with sqlite3.connect(d.DB_FILE,timeout=8) as db:
                    db.execute('DELETE FROM phantom_launch_sessions WHERE wallet=?',
                               (flow['wallet'],))
                    db.execute("UPDATE phantom_launch_links SET status='cancelled' WHERE token=?",
                               (flow['token'],))
            return fail('Phantom approval was cancelled or expired. Your saved token was not changed. Tap Approve launch again.',409)
        if (not isinstance(data.get('nonce'),str) or
                not isinstance(data.get('data'),str)):
            return fail('Phantom returned incomplete approval',400)
        stage=data.get('step')
        if stage not in ('connect','sign') or flow['status']!=stage:
            return fail('Phantom approval was already processed or is out of sequence',409)
        sk=fernet.decrypt(flow['secret'])
        try:
            if stage=='connect':
                pk=data.get('phantom_encryption_public_key')
                decoded=decrypt(sk,pk,data['nonce'],data['data'])
                if decoded.get('public_key')!=flow['wallet'] or not decoded.get('session'):
                    return fail('Phantom wallet differs from the logged-in OrcAgent wallet',409)
                session=decoded['session']
                if not isinstance(session,str) or len(session)>1024:
                    return fail('Invalid Phantom session',400)
                url=sign_url(flow,sk,pk,session)
                record=fernet.encrypt(json.dumps({
                    'sk':b58enc(sk),'pk':pk,'session':session}).encode())
                with sqlite3.connect(d.DB_FILE,timeout=8) as db:
                    db.execute('BEGIN IMMEDIATE')
                    cur=db.execute("""UPDATE phantom_launch_links SET status='sign'
                       WHERE token=? AND status='connect'""",(flow['token'],))
                    if cur.rowcount!=1:return fail('This approval was already processed',409)
                    db.execute("""INSERT INTO phantom_launch_sessions(wallet,secret,saved_at)
                       VALUES (?,?,?) ON CONFLICT(wallet) DO UPDATE SET
                       secret=excluded.secret,saved_at=excluded.saved_at""",
                       (flow['wallet'],record,int(time.time())))
                return jsonify(ok=True,url=url,step='sign')
            record=session_for(flow['wallet'])
            if not record or record[0]!=sk:
                return fail('Phantom session changed. Try the saved launch again.',409)
            decoded=decrypt(sk,record[1],data['nonce'],data['data'])
            row,original_b64=current(flow)
            if original_b64 is None:return fail('Prepared transaction changed. Check the saved token first.',409)
            original=Transaction.from_bytes(base64.b64decode(original_b64,validate=True))
            wallet=Pubkey.from_string(flow['wallet'])
            if (str(original.message.account_keys[0])!=flow['wallet'] or
                any(not sig.verify(original.message.account_keys[index],bytes(original.message))
                    for index,sig in enumerate(original.signatures) if index>0)):
                return fail('Stored token transaction signature is invalid',409)
            # New Phantom signAndSendTransaction returns a signature, not a
            # serialized transaction. Verify that it signed the EXACT saved
            # message before accepting its chain submission as pending.
            signed_by_wallet=isinstance(decoded.get('signature'),str)
            if signed_by_wallet:
                signature=decoded['signature']
                if not SIG.fullmatch(signature) or not Signature.from_string(signature).verify(
                        wallet,bytes(original.message)):
                    return fail('Phantom signature does not match your token launch',409)
            else:
                # Phantom returns the signed transaction; validate the exact
                # saved message and both signatures before any RPC relay.
                signed=b58dec(decoded.get('transaction'))
                if not 1<=len(signed)<=1232:raise ValueError('Invalid transaction size')
                tx=Transaction.from_bytes(signed)
                if blockhash_valid is not None and not (
                    still_valid(original_b64,(claim_for(flow) or {'created_at':0})['created_at'],claim_read=True)
                    if flow['stage']=='claim' else blockhash_valid(original_b64)):
                    return fail('Phantom approval expired before submission. Reopen this SAME saved token and retry safely.',409)
                # Phantom may add its standard wrapper to a CLAIM (compute
                # budget + Lighthouse guard). The Pump claim itself must stay
                # identical; launches must still match byte-for-byte.
                same=bytes(tx.message)==bytes(original.message)
                wrapped=(not same and flow['stage']=='claim' and claim_wrapper_ok is not None
                         and len(original.signatures)==1 and len(tx.signatures)==1
                         and claim_wrapper_ok(tx.message,original.message,flow['wallet']))
                if not (same or wrapped) or not all(tx.verify_with_results()):
                    return fail('Phantom signature did not match this exact token launch',409)
                if len(tx.signatures)!=len(original.signatures) or tx.signatures[1:]!=original.signatures[1:]:
                    return fail('Ephemeral token signature changed',409)
                signature=str(tx.signatures[0])
                if not SIG.fullmatch(signature):return fail('Invalid Phantom transaction signature',400)
        except Exception:
            # Includes NaCl CryptoError and malformed solders transaction
            # input. Never log or return encrypted Phantom payloads.
            return fail('Phantom returned an invalid transaction or wallet session',400)
        # Claim signatures must be persisted before broadcasting so a lost RPC
        # response cannot produce a second payable claim transaction.
        if flow['stage']=='claim':
            claim=claim_for(flow)
            if not claim or claim['status']!='prepared' or claim['signature']:
                return fail('Claim status changed. Check claim history.',409)
            with sqlite3.connect(d.DB_FILE,timeout=8) as db:
                db.execute('BEGIN IMMEDIATE')
                protected=fernet.encrypt(signed) if not signed_by_wallet else None
                link=db.execute('''UPDATE phantom_launch_links SET status='submitted',
                    signature=?,signed_tx=? WHERE token=? AND status='sign' ''',
                    (signature,protected,flow['token']))
                updated=db.execute('''UPDATE token_reward_claims SET status='submitted',signature=?
                    WHERE id=? AND launch_id=? AND wallet=? AND status='prepared' AND signature='' ''',
                    (signature,flow['claim_id'],flow['launch_id'],flow['wallet']))
                if link.rowcount!=1 or updated.rowcount!=1:
                    db.rollback()
                    return fail('Claim was already submitted. Check claim history.',409)
            if not signed_by_wallet:
                from launch_delivery import relay_identical_signed
                delivery=relay_identical_signed(signed,signature,[
                    os.getenv('ORCA_LAUNCH_RPC',''),
                    getattr(d,'SOLANA_RPC_URL','') or getattr(d,'SOLANA_RPC',''),
                    'https://solana-rpc.publicnode.com',
                    'https://api.mainnet-beta.solana.com'])
                if not delivery:
                    return jsonify(ok=True,submitted=True,signature=signature,
                        msg='Claim signature saved. Solana delivery is uncertain. Check claim history before retrying.')
            return jsonify(ok=True,submitted=True,signature=signature,
                msg='Claim submitted to Solana. Return to OrcAgent and check claim history for the confirmed USDC receipt.')

        # Lock the mint/stage to this signature BEFORE broadcasting. If RPC times
        # out, never prepare or submit a DIFFERENT token as a blind retry.
        sig_field='launch_signature' if flow['stage']=='create' else 'finalize_signature'
        from_status='prepared' if flow['stage']=='create' else 'finalize_prepared'
        pending='submitted' if flow['stage']=='create' else 'finalize_submitted'
        with sqlite3.connect(d.DB_FILE,timeout=8) as db:
            db.execute('BEGIN IMMEDIATE')
            protected_tx=fernet.encrypt(signed) if not signed_by_wallet else None
            cur=db.execute("""UPDATE phantom_launch_links SET status='submitted',signature=?,signed_tx=?
                              WHERE token=? AND status='sign'""",(signature,protected_tx,flow['token']))
            if cur.rowcount!=1:return fail('This Phantom approval was already processed',409)
            cur=db.execute(f"""UPDATE token_launches SET status=?,{sig_field}=?
                WHERE id=? AND wallet=? AND status=? AND {sig_field}='' """,
                (pending,signature,flow['launch_id'],flow['wallet'],from_status))
            if cur.rowcount!=1:
                db.rollback()
                return fail('Launch was submitted elsewhere. Check existing transaction.',409)
        # Sign-only links need relay. Identical bytes keep the same signature
        # even if failover sends them to more than one RPC. Never skip preflight.
        if not signed_by_wallet:
            from launch_delivery import relay_identical_signed
            delivery_reasons=[]
            delivery=relay_identical_signed(
                signed,signature,[os.getenv('ORCA_LAUNCH_RPC',''),
                      getattr(d,'SOLANA_RPC_URL','') or getattr(d,'SOLANA_RPC',''),
                      'https://solana-rpc.publicnode.com',
                      'https://api.mainnet-beta.solana.com'],reasons=delivery_reasons)
            if not delivery:
                reason=next((x for x in delivery_reasons if x not in
                    ('RPC temporarily unavailable','RPC rejected the transaction')),
                    'RPC delivery could not be verified')
                return jsonify(ok=True,submitted=True,signature=signature,
                    msg=reason+'. Your signed launch remains saved. Use Check transaction; do not create another token.')

        try:
            if check_signature(signature,row,flow['stage']) and (
                mint_exists(row['mint']) if flow['stage']=='create'
                else sharing_check(row['mint'],row['wallet'],row['community_wallet'],
                                   row['community_bps'])):
                target=('pending_shares' if row['reward_mode']=='community' else 'live') if flow['stage']=='create' else 'live'
                with sqlite3.connect(d.DB_FILE,timeout=8) as db:
                    db.execute("""UPDATE token_launches SET status=?,
                         finalized_at=CASE WHEN ?='live' THEN ? ELSE finalized_at END
                         WHERE id=? AND wallet=? AND status=?""",
                         (target,target,int(time.time()),flow['launch_id'],
                          flow['wallet'],pending))
                return jsonify(ok=True,confirmed=True,signature=signature,
                               msg='Token launch confirmed on Solana.')
        except (RuntimeError,ValueError):
            pass
        return jsonify(ok=True,submitted=True,signature=signature,
                       msg='Submitted to Solana. Check transaction for final confirmation.')


def remember_authenticated_session(db_file,encryption_key,wallet,record):
    """Cache the existing Phantom login connection only AFTER wallet/set has
    verified that wallet's actual Ed25519 login signature. No new connect tap
    is required for a previously connected user on their next token launch.
    """
    if (not isinstance(record,dict) or record.get('wallet_address')!=wallet
        or not isinstance(record.get('sk'),bytes)
        or len(record['sk'])!=32 or not record.get('phantom_pk')
        or not record.get('session') or not encryption_key):
        return False
    protected=Fernet(encryption_key.encode()).encrypt(json.dumps({
        'sk':b58enc(record['sk']),'pk':record['phantom_pk'],
        'session':record['session']}).encode())
    with sqlite3.connect(db_file,timeout=8) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS phantom_launch_sessions(
          wallet TEXT PRIMARY KEY, secret BLOB NOT NULL, saved_at INTEGER NOT NULL)""")
        db.execute("""INSERT INTO phantom_launch_sessions(wallet,secret,saved_at)
              VALUES (?,?,?) ON CONFLICT(wallet) DO UPDATE SET
              secret=excluded.secret,saved_at=excluded.saved_at""",
              (wallet,protected,int(time.time())))
    return True
