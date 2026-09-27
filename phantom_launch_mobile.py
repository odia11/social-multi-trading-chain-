"""Phantom mobile-browser token launch signing without an injected provider.

Two-step Phantom connect (once per wallet) / signAndSendTransaction links.
Phantom broadcasts new launches; server relays ONLY legacy already-signed
transactions with the identical bytes after owner signature validation.
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

def install(d,lookup,check_signature,mint_exists,sharing_check,blockhash_valid=None):
    app=d.app
    fernet=Fernet(os.environ['ENCRYPTION_KEY'].encode())
    with sqlite3.connect(d.DB_FILE) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS phantom_launch_links(
          token TEXT PRIMARY KEY, launch_id TEXT NOT NULL, wallet TEXT NOT NULL,
          stage TEXT NOT NULL, digest TEXT NOT NULL, secret BLOB NOT NULL,
          created_at INTEGER NOT NULL, status TEXT NOT NULL,
          signature TEXT NOT NULL DEFAULT '')""")
        db.execute("""CREATE TABLE IF NOT EXISTS phantom_launch_sessions(
          wallet TEXT PRIMARY KEY, secret BLOB NOT NULL, saved_at INTEGER NOT NULL)""")

    def fail(reason,code=400):return jsonify(ok=False,msg=reason),code

    def load(token):
        if not isinstance(token,str) or not TOKEN.fullmatch(token):return None
        with sqlite3.connect(d.DB_FILE) as db:
            db.row_factory=sqlite3.Row
            found=db.execute('SELECT * FROM phantom_launch_links WHERE token=?',(token,)).fetchone()
        return dict(found) if found else None

    def current(flow):
        row=lookup(flow['launch_id'],flow['wallet'])
        if not row:return None,None
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
            'token':flow['token'],'step':step})

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
        # Phantom signs AND submits via its wallet RPC. The old sign-only path
        # left users on a perpetual pending state when OrcAgent RPC timed out.
        nonce,payload=encode({'transaction':transaction,'session':session,
             'sendOptions':{'skipPreflight':False,'preflightCommitment':'confirmed','maxRetries':2}},sk,phantom_pk)
        return 'https://phantom.app/ul/v1/signAndSendTransaction?'+urlencode({
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
              'status':'sign' if cached else 'connect'}
        with sqlite3.connect(d.DB_FILE,timeout=8) as db:
            db.execute('DELETE FROM phantom_launch_links WHERE created_at<?',
                       (int(time.time())-TTL,))
            db.execute("""INSERT INTO phantom_launch_links
              (token,launch_id,wallet,stage,digest,secret,created_at,status)
              VALUES (:token,:launch_id,:wallet,:stage,:digest,:secret,:created_at,:status)""",
              flow)
        if cached:
            try:url=sign_url(flow,sk,pk,session)
            except (ValueError,KeyError):
                return fail('Prepared launch expired. Use the saved launch to try again.',409)
        else:url=connect_url(flow)
        return jsonify(ok=True,url=url,requires_connect=not bool(cached))

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
            if original_b64 is None:return fail('Prepared launch changed. Check the saved token first.',409)
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
                # Backward-compatible callback for already-open signTransaction
                # links issued before this deployment. Those need RPC relay.
                signed=b58dec(decoded.get('transaction'))
                if not 1<=len(signed)<=1232:raise ValueError('Invalid transaction size')
                tx=Transaction.from_bytes(signed)
                if blockhash_valid is not None and not blockhash_valid(original_b64):
                    return fail('Phantom approval expired before submission. Reopen this SAME saved token and retry safely.',409)
                if bytes(tx.message)!=bytes(original.message) or not all(tx.verify_with_results()):
                    return fail('Phantom signature did not match this exact token launch',409)
                if len(tx.signatures)!=len(original.signatures) or tx.signatures[1:]!=original.signatures[1:]:
                    return fail('Ephemeral token signature changed',409)
                signature=str(tx.signatures[0])
                if not SIG.fullmatch(signature):return fail('Invalid Phantom transaction signature',400)
        except Exception:
            # Includes NaCl CryptoError and malformed solders transaction
            # input. Never log or return encrypted Phantom payloads.
            return fail('Phantom returned an invalid transaction or wallet session',400)
        # Lock the mint/stage to this signature BEFORE broadcasting. If RPC times
        # out, never prepare or submit a DIFFERENT token as a blind retry.
        sig_field='launch_signature' if flow['stage']=='create' else 'finalize_signature'
        from_status='prepared' if flow['stage']=='create' else 'finalize_prepared'
        pending='submitted' if flow['stage']=='create' else 'finalize_submitted'
        with sqlite3.connect(d.DB_FILE,timeout=8) as db:
            db.execute('BEGIN IMMEDIATE')
            cur=db.execute("""UPDATE phantom_launch_links SET status='submitted',signature=?
                              WHERE token=? AND status='sign'""",(signature,flow['token']))
            if cur.rowcount!=1:return fail('This Phantom approval was already processed',409)
            cur=db.execute(f"""UPDATE token_launches SET status=?,{sig_field}=?
                WHERE id=? AND wallet=? AND status=? AND {sig_field}='' """,
                (pending,signature,flow['launch_id'],flow['wallet'],from_status))
            if cur.rowcount!=1:
                db.rollback()
                return fail('Launch was submitted elsewhere. Check existing transaction.',409)
        # New mobile launches are broadcast directly BY Phantom, not via
        # OrcAgent's throttled RPC. Never send the user's signed transaction
        # twice or claim a token is live merely because Phantom returned a sig.
        if not signed_by_wallet:
            # Legacy in-flight signTransaction callbacks still need relay.
            # Use only the identical signed bytes/signature, with failover on
            # transport/rate-limit failures. Never skip preflight.
            from launch_delivery import relay_identical_signed
            delivery=relay_identical_signed(
                signed,signature,[getattr(d,'SOLANA_RPC_URL','') or getattr(d,'SOLANA_RPC',''),
                      'https://solana-rpc.publicnode.com',
                      'https://api.mainnet-beta.solana.com'])
            if not delivery:
                return jsonify(ok=True,submitted=True,signature=signature,
                    msg='RPC delivery uncertain. Keep your original signature; use Check transaction.')

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
