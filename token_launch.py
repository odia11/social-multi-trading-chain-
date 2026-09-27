"""USDC-first Pump token launch, with wallet-signed on-chain stages.

No server key signs for the creator. No platform reward is invented or
misclassified as an OrcAgent trading fee. The feature is disabled until a
mainnet preflight is authorized via ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED=1.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import secrets
import sqlite3
import subprocess
import time
from contextlib import closing
from PIL import Image, ImageOps
from solders.pubkey import Pubkey
from solders.transaction import Transaction as SolanaTransaction
import requests
from flask import abort, jsonify, request, make_response, redirect

USDC_MINT='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
WSOL_MINT='So11111111111111111111111111111111111111112'
PUMP_PROGRAM='6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P'
_MODES={'creator','community','holder'}
_ASSETS={'USDC','SOL'}
_B58=re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
_SIG=re.compile(r'^[1-9A-HJ-NP-Za-km-z]{85,90}$')
_DRAFT_ID=re.compile(r'^[0-9a-f]{32}$')


def _validate_form(d, data, wallet):
    if not isinstance(data,dict):raise ValueError('Invalid token details')
    name=data.get('name'); symbol=data.get('symbol'); desc=data.get('description','')
    mode=data.get('reward_mode','community'); quote=data.get('quote_asset','USDC')
    community=data.get('community_wallet',''); bps=data.get('community_bps',0)
    if not isinstance(name,str) or not 2<=len(name.strip())<=32:
        raise ValueError('Token name must be 2–32 characters')
    if not isinstance(symbol,str) or not re.fullmatch(r'[A-Za-z0-9]{2,10}',symbol):
        raise ValueError('Symbol must be 2–10 letters or numbers')
    if not isinstance(desc,str) or len(desc)>280:
        raise ValueError('Description must be 280 characters or fewer')
    if not isinstance(mode,str) or not isinstance(quote,str) or mode not in _MODES or quote not in _ASSETS:
        raise ValueError('Invalid reward mode or quote asset')
    if mode=='community':
        if not isinstance(community,str) or not d.is_valid_solana_address(community) or community==wallet:
            raise ValueError('Enter a different, valid Solana community wallet')
        if isinstance(bps,bool) or not isinstance(bps,int) or not 1<=bps<=9999:
            raise ValueError('Community share must be 1–9999 basis points')
    else:
        community=''; bps=0
    return name.strip(),symbol.upper(),desc.strip(),mode,quote,community,bps


def _clean_icon(value):
    if not isinstance(value,str) or not value.startswith('data:image/') or len(value)>1_600_000:
        raise ValueError('Upload a PNG, JPG or WebP token image (max 1 MB)')
    try:
        prefix,payload=value.split(',',1)
        if prefix not in ('data:image/png;base64','data:image/jpeg;base64','data:image/webp;base64'):
            raise ValueError
        raw=base64.b64decode(payload,validate=True)
        if len(raw)>1_000_000:raise ValueError
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ('PNG','JPEG','WEBP') or image.width*image.height>12_000_000:
                raise ValueError
            frame=ImageOps.exif_transpose(image)
            frame.thumbnail((512,512))
            out=io.BytesIO()
            if frame.mode not in ('RGB','RGBA'):frame=frame.convert('RGBA')
            frame.save(out,format='WEBP',quality=82,method=4)
        icon=out.getvalue()
        if len(icon)>320_000:raise ValueError
        return icon
    except Exception as exc:
        raise ValueError('Invalid token image. Upload a smaller PNG, JPG or WebP.') from exc


def install(d):
    app=d.app
    if getattr(app,'_orca_token_launch_installed',False):return
    app._orca_token_launch_installed=True
    with sqlite3.connect(d.DB_FILE) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS token_launches (
            id TEXT PRIMARY KEY,
            wallet TEXT NOT NULL,
            client_nonce TEXT NOT NULL,
            name TEXT NOT NULL,
            symbol TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            icon_webp BLOB NOT NULL,
            reward_mode TEXT NOT NULL,
            quote_asset TEXT NOT NULL,
            community_wallet TEXT NOT NULL DEFAULT '',
            community_bps INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'draft',
            mint TEXT UNIQUE,
            prepare_tx_b64 TEXT NOT NULL DEFAULT '',
            finalize_tx_b64 TEXT NOT NULL DEFAULT '',
            launch_signature TEXT NOT NULL DEFAULT '',
            finalize_signature TEXT NOT NULL DEFAULT '',
            prepared_at INTEGER NOT NULL DEFAULT 0,
            finalized_at INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            UNIQUE(wallet,client_nonce)
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_token_launch_owner ON token_launches(wallet,created_at)')
        # Claims are a separate ledger, NEVER another OrcAgent trade/fee entry.
        # No amount is reported as received until its precise chain transaction
        # confirms; accrued_raw is only a dated pre-claim observation.
        conn.execute('''CREATE TABLE IF NOT EXISTS token_reward_claims (
            id TEXT PRIMARY KEY, launch_id TEXT NOT NULL,
            wallet TEXT NOT NULL, mint TEXT NOT NULL,
            quote_asset TEXT NOT NULL, reward_mode TEXT NOT NULL,
            accrued_raw TEXT NOT NULL DEFAULT '0',
            accrued_scope TEXT NOT NULL DEFAULT '',
            transaction_b64 TEXT NOT NULL,
            signature TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'prepared',
            created_at INTEGER NOT NULL, confirmed_at INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(launch_id) REFERENCES token_launches(id)
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_token_reward_claims_wallet ON token_reward_claims(wallet,created_at)')

    def enabled(wallet=None):
        # Normal users always remain in safe draft-only mode during a pilot.
        # A pilot requires BOTH an explicit switch and an exact, authenticated
        # wallet allowlist. No user-supplied wallet/body/header can override it.
        if os.getenv('ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED','0')=='1':
            return True
        if os.getenv('ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_ENABLED','0')!='1':
            return False
        w=wallet or identity()
        raw=os.getenv('ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_WALLETS','')
        wallets={candidate.strip() for candidate in raw.split(',') if candidate.strip()}
        return bool(w and w in wallets and d.is_valid_solana_address(w))

    def fail(message,status=400):
        return jsonify(ok=False,msg=str(message)[:220]),status

    def identity():
        w=d._authenticated_wallet()
        return w if w and d.is_valid_solana_address(w) else ''

    def csrf():
        return d._validate_csrf(request.headers.get('X-CSRF-Token',''))

    def lookup(draft_id,wallet):
        if not _DRAFT_ID.fullmatch(draft_id):return None
        with closing(sqlite3.connect(d.DB_FILE)) as conn:
            conn.row_factory=sqlite3.Row
            row=conn.execute('SELECT * FROM token_launches WHERE id=? AND wallet=?',
                             (draft_id,wallet)).fetchone()
        return dict(row) if row else None

    def public_row(row):
        return {k:row[k] for k in ('id','name','symbol','description','reward_mode',
                   'quote_asset','community_wallet','community_bps','status','mint',
                   'launch_signature','finalize_signature','created_at','error')}

    def rpc(method,params):
        # Configured Solana RPC only. Never allow a URL from the browser.
        endpoint=(getattr(d,'SOLANA_RPC_URL','') or d.SOLANA_RPC)
        try:
            resp=requests.post(endpoint,json={'jsonrpc':'2.0','id':1,
                 'method':method,'params':params},timeout=9)
            resp.raise_for_status()
            result=resp.json()
            if not isinstance(result,dict):raise RuntimeError('Solana RPC returned invalid response')
            if result.get('error'):raise RuntimeError('Solana RPC rejected '+method)
            return result.get('result')
        except (requests.RequestException,ValueError,RuntimeError) as exc:
            raise RuntimeError('Solana network response unavailable; retry later') from exc

    def build_tx(row,stage):
        block=rpc('getLatestBlockhash',[{'commitment':'confirmed'}])
        blockhash=((block or {}).get('value') or {}).get('blockhash')
        if not blockhash:raise RuntimeError('No recent Solana blockhash')
        data={k:row[k] for k in ('wallet','name','symbol','reward_mode',
                                  'quote_asset','community_wallet','community_bps')}
        data.update(stage=stage,blockhash=blockhash,mint=row['mint'],
                    uri='https://orcagent.fun/token-launch/metadata/'+row['id'])
        path=os.path.join(d.BASE,'pump_adapter','build-launch.cjs')
        try:
            r=subprocess.run(['node',path],input=json.dumps(data),text=True,
                capture_output=True,timeout=14,cwd=os.path.join(d.BASE,'pump_adapter'),
                check=False)
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise RuntimeError('Token builder unavailable') from exc
        if r.returncode or not r.stdout:
            raise RuntimeError('Token builder rejected this configuration. No transaction was sent.')
        built=json.loads(r.stdout)
        if built.get('quote_mint') != (USDC_MINT if row['quote_asset']=='USDC' else WSOL_MINT):
            raise RuntimeError('Token builder returned the wrong trading currency')
        if stage=='finalize' and built.get('mint')!=row['mint']:
            raise RuntimeError('Token builder returned the wrong token')
        if not built.get('transaction_b64') or built.get('transaction_bytes',0)>1232:
            raise RuntimeError('Invalid Solana transaction')
        return built

    def blockhash_valid(transaction_b64):
        """Reject stale instructions using the actual Solana blockhash gate.

        We only re-prepare an unsigned action if its original blockhash has
        expired AND the on-chain action was not executed. Never guess based
        only on the wall-clock, as blockhash lifetime is chain-dependent.
        """
        try:
            raw=base64.b64decode(transaction_b64,validate=True)
            blockhash=str(SolanaTransaction.from_bytes(raw).message.recent_blockhash)
        except (ValueError,base64.binascii.Error) as exc:
            raise RuntimeError('Stored transaction could not be verified') from exc
        answer=rpc('isBlockhashValid',[blockhash,{'commitment':'confirmed'}])
        if not isinstance(answer,dict) or not isinstance(answer.get('value'),bool):
            raise RuntimeError('Solana blockhash validity unavailable')
        return answer['value']

    def sharing_check(mint,wallet,community,bps):
        helper=os.path.join(d.BASE,'pump_adapter','check-sharing.cjs')
        def run(data):
            try:
                p=subprocess.run(['node',helper],input=json.dumps(data),text=True,
                    capture_output=True,timeout=7,cwd=os.path.dirname(helper))
                if p.returncode:raise RuntimeError('Share configuration could not be verified')
                return json.loads(p.stdout)
            except (OSError,subprocess.TimeoutExpired,ValueError) as exc:
                raise RuntimeError('Share configuration could not be verified') from exc
        info=run({'action':'address','mint':mint})
        account=rpc('getAccountInfo',[info['address'],{'encoding':'base64','commitment':'confirmed'}])
        state=(account or {}).get('value')
        if not state or state.get('owner')!=info['program']:
            raise RuntimeError('Fee-sharing account has not been confirmed')
        decoded=run({'action':'verify','mint':mint,'data_b64':state['data'][0]})
        shares=decoded.get('shares',[])
        return (decoded.get('mint')==mint and decoded.get('admin_revoked') is True
                and len(shares)==2
                and {s['wallet']:s['bps'] for s in shares}
                    == {wallet:10000-bps,community:bps})

    def mint_exists(mint):
        program=Pubkey.from_string(PUMP_PROGRAM)
        minted=Pubkey.from_string(mint)
        pda,_=Pubkey.find_program_address([b'bonding-curve',bytes(minted)],program)
        info=rpc('getAccountInfo',[str(pda),{'encoding':'base64','commitment':'confirmed'}])
        return bool((info or {}).get('value') and info['value'].get('owner')==PUMP_PROGRAM)

    def check_signature(signature,row,stage):
        """Check the *exact* prepared transaction, not merely any Pump trade.

        A user-supplied signature for some other swap involving the same mint
        must never mark a token launched or a fee split finalized. The two
        signed messages must match byte-for-byte; RPC confirmed transaction
        and the creator's wallet signature prove this was the agreed action.
        """
        if not isinstance(signature,str) or not _SIG.fullmatch(signature):
            raise ValueError('Invalid transaction signature')
        stored=row['prepare_tx_b64'] if stage=='create' else row['finalize_tx_b64']
        if not stored:raise ValueError('No prepared transaction for this action')
        result=rpc('getTransaction',[signature,{'encoding':'base64',
                         'commitment':'confirmed','maxSupportedTransactionVersion':0}])
        if not result:return False
        if (result.get('meta') or {}).get('err') is not None:
            raise ValueError('The Solana transaction failed')
        try:
            raw=result['transaction'][0]
            signed=SolanaTransaction.from_bytes(base64.b64decode(raw,validate=True))
            prepared=SolanaTransaction.from_bytes(base64.b64decode(stored,validate=True))
            if bytes(signed.message)!=bytes(prepared.message):
                raise ValueError('Signed transaction does not match this launch')
            if str(signed.signatures[0])!=signature or not all(signed.verify_with_results()):
                raise ValueError('Missing or invalid creator wallet signature')
            keys=[str(key) for key in signed.message.account_keys]
            if row['wallet'] not in keys or keys[0]!=row['wallet']:
                raise ValueError('Creator wallet must authorize the transaction')
            # For creator claims the Pump vault covers ALL tokens created by
            # the wallet, and the transaction need not include this launch's
            # mint. Exact prepared-message comparison is the binding proof.
            # Launch/finalization, unlike claims, MUST include our mint and
            # Pump's bonding-curve program ID.
            if stage!='claim' and (row['mint'] not in keys or PUMP_PROGRAM not in keys):
                raise ValueError('Unexpected token or Pump program')
        except (IndexError,KeyError,TypeError,base64.binascii.Error) as exc:
            raise ValueError('Unrecognized on-chain transaction') from exc
        return True

    @app.get('/token-launch')
    def token_launch_page():
        wallet=identity()
        if not wallet:return redirect('/?connect=1')
        return d._render_no_cache('token_launch.html',wallet=wallet,
            csrf_token=d._get_csrf_token(),launch_enabled=enabled(),
            navbar_html=d._navbar_html)

    @app.get('/api/token-launch/config')
    @d.rate_limit(30,60)
    def launch_config():
        if not identity():return fail('Connect your wallet',401)
        return jsonify(ok=True,enabled=enabled(),default_quote='USDC',
           default_reward_mode='community',sol_conversion='manual_only',
           fee_disclosure='Pump fees and Solana network/rent fees apply. OrcAgent does not charge an extra launch fee.',
           capabilities={'creator':True,'community':True,'holder':True})

    @app.post('/api/token-launch/draft')
    @d.rate_limit(6,60)
    def create_draft():
        wallet=identity()
        if not wallet:return fail('Connect your wallet',401)
        if not csrf():return fail('CSRF validation failed',403)
        if request.content_length and request.content_length>1_750_000:
            return fail('Token details too large',413)
        body=request.get_json(silent=True)
        try:
            name,symbol,desc,mode,quote,community,bps=_validate_form(d,body,wallet)
            nonce=body.get('client_nonce')
            if not isinstance(nonce,str) or not re.fullmatch('[a-zA-Z0-9_-]{16,80}',nonce):
                raise ValueError('Invalid launch request identifier')
            icon=_clean_icon(body.get('image_data'))
        except ValueError as exc:return fail(exc)
        launch_id=secrets.token_hex(16)
        with sqlite3.connect(d.DB_FILE,timeout=8) as conn:
            conn.row_factory=sqlite3.Row
            conn.execute('BEGIN IMMEDIATE')
            existing=conn.execute('SELECT * FROM token_launches WHERE wallet=? AND client_nonce=?',
                                  (wallet,nonce)).fetchone()
            if existing:return jsonify(ok=True,draft=public_row(existing),reused=True)
            # Prevent one wallet filling the persistent production database
            # with unlimited image blobs by saving drafts without launching.
            drafts=conn.execute('SELECT COUNT(*) FROM token_launches WHERE wallet=? AND status=?',
                                (wallet,'draft')).fetchone()[0]
            if drafts>=20:
                return fail('You have 20 saved drafts. Launching more tokens requires clearing old drafts.',409)
            conn.execute('''INSERT INTO token_launches
              (id,wallet,client_nonce,name,symbol,description,icon_webp,reward_mode,
               quote_asset,community_wallet,community_bps,created_at)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
              (launch_id,wallet,nonce,name,symbol,desc,icon,mode,quote,community,bps,int(time.time())))
        return jsonify(ok=True,draft=public_row(lookup(launch_id,wallet))),201

    @app.get('/token-launch/metadata/<launch_id>')
    @d.rate_limit(60,60)
    def launch_metadata(launch_id):
        if not _DRAFT_ID.fullmatch(launch_id):abort(404)
        with closing(sqlite3.connect(d.DB_FILE)) as conn:
            row=conn.execute('SELECT name,symbol,description FROM token_launches WHERE id=?',
                             (launch_id,)).fetchone()
        if not row:abort(404)
        resp=jsonify(name=row[0],symbol=row[1],description=row[2],
                   image='https://orcagent.fun/token-launch/icon/'+launch_id,
                   external_url='https://orcagent.fun/token-launch')
        resp.headers['Cache-Control']='public,max-age=300'
        return resp

    @app.get('/token-launch/icon/<launch_id>')
    @d.rate_limit(60,60)
    def launch_icon(launch_id):
        if not _DRAFT_ID.fullmatch(launch_id):abort(404)
        with closing(sqlite3.connect(d.DB_FILE)) as conn:
            row=conn.execute('SELECT icon_webp FROM token_launches WHERE id=?',(launch_id,)).fetchone()
        if not row:abort(404)
        resp=make_response(row[0]);resp.headers['Content-Type']='image/webp'
        resp.headers['Cache-Control']='public,max-age=604800'
        resp.headers['X-Content-Type-Options']='nosniff'
        return resp

    @app.post('/api/token-launch/<launch_id>/delete-draft')
    @d.rate_limit(10,60)
    def delete_launch_draft(launch_id):
        wallet=identity()
        if not wallet:return fail('Connect your wallet',401)
        if not csrf():return fail('CSRF validation failed',403)
        if not _DRAFT_ID.fullmatch(launch_id):return fail('Invalid draft ID')
        # NEVER delete a prepared/submitted/live token or its durable metadata.
        with sqlite3.connect(d.DB_FILE) as conn:
            result=conn.execute('DELETE FROM token_launches WHERE id=? AND wallet=? AND status=?',
                                (launch_id,wallet,'draft'))
        if result.rowcount!=1:return fail('Only your own unsent draft can be deleted',409)
        return jsonify(ok=True)

    @app.get('/api/token-launch/mine')
    @d.rate_limit(30,60)
    def my_launches():
        wallet=identity()
        if not wallet:return fail('Connect your wallet',401)
        with closing(sqlite3.connect(d.DB_FILE)) as conn:
            conn.row_factory=sqlite3.Row
            rows=conn.execute('SELECT * FROM token_launches WHERE wallet=? ORDER BY created_at DESC LIMIT 40',
                              (wallet,)).fetchall()
        return jsonify(ok=True,launches=[public_row(r) for r in rows])

    @app.post('/api/token-launch/<launch_id>/prepare')
    @d.rate_limit(4,60)
    def prepare_launch(launch_id):
        wallet=identity()
        if not wallet:return fail('Connect your wallet',401)
        if not csrf():return fail('CSRF validation failed',403)
        if not enabled():return fail('Token Launch is in preflight; no mainnet transaction can be prepared',503)
        row=lookup(launch_id,wallet)
        if not row:return fail('Launch not found',404)
        if row['status']=='prepared' and not row['launch_signature']:
            # Phantom rejection/suspended mobile app must not permanently
            # strand the creator's unsent token. Return the identical signed
            # mint transaction while its blockhash might still be valid.
            if time.time()-row['prepared_at']<45:
                return jsonify(ok=True,mint=row['mint'],transaction_b64=row['prepare_tx_b64'],
                    quote_asset=row['quote_asset'],reward_mode=row['reward_mode'],
                    needs_finalization=row['reward_mode']=='community',expires_in=60,reused=True)
            try:
                if blockhash_valid(row['prepare_tx_b64']):
                    return jsonify(ok=True,mint=row['mint'],transaction_b64=row['prepare_tx_b64'],
                        quote_asset=row['quote_asset'],reward_mode=row['reward_mode'],
                        needs_finalization=row['reward_mode']=='community',expires_in=45,reused=True)
                if mint_exists(row['mint']):
                    return fail('This token already exists on Pump. Recover its signature from Phantom before retrying.',409)
            except RuntimeError as exc:return fail(exc,503)
            with sqlite3.connect(d.DB_FILE,timeout=8) as conn:
                cur=conn.execute('''UPDATE token_launches SET status='draft',mint=NULL,
                      prepare_tx_b64='',prepared_at=0
                      WHERE id=? AND wallet=? AND status='prepared' AND mint=?
                      AND launch_signature='' ''',(launch_id,wallet,row['mint']))
                if cur.rowcount!=1:return fail('Launch changed during recovery; reload.',409)
            row=lookup(launch_id,wallet)
        if row['status']!='draft':return fail('This launch was already submitted; check its status before retrying',409)
        try:built=build_tx(row,'create')
        except RuntimeError as exc:return fail(exc,503)
        with sqlite3.connect(d.DB_FILE,timeout=8) as conn:
            cur=conn.execute('''UPDATE token_launches
                  SET mint=?, prepare_tx_b64=?, status='prepared', prepared_at=?
                  WHERE id=? AND wallet=? AND status='draft' ''',
                  (built['mint'],built['transaction_b64'],int(time.time()),launch_id,wallet))
            if cur.rowcount!=1:return fail('This launch is already being prepared. Reload status.',409)
        return jsonify(ok=True,mint=built['mint'],transaction_b64=built['transaction_b64'],
            quote_asset=row['quote_asset'],reward_mode=row['reward_mode'],
            needs_finalization=built.get('needs_fee_share_finalization',False),
            expires_in=100)

    @app.post('/api/token-launch/<launch_id>/prepare-finalize')
    @d.rate_limit(5,60)
    def prepare_finalization(launch_id):
        wallet=identity()
        if not wallet:return fail('Connect your wallet',401)
        if not csrf():return fail('CSRF validation failed',403)
        if not enabled():return fail('Token Launch is in preflight',503)
        row=lookup(launch_id,wallet)
        if not row:return fail('Launch not found',404)
        if row['status']=='finalize_prepared' and not row['finalize_signature']:
            if time.time()-row['prepared_at']<45:
                return jsonify(ok=True,mint=row['mint'],
                    transaction_b64=row['finalize_tx_b64'],expires_in=60,reused=True)
            try:
                if blockhash_valid(row['finalize_tx_b64']):
                    return jsonify(ok=True,mint=row['mint'],transaction_b64=row['finalize_tx_b64'],
                        expires_in=45,reused=True)
                if sharing_check(row['mint'],wallet,row['community_wallet'],row['community_bps']):
                    return fail('Fee sharing is already final on-chain. Recover the transaction signature from Phantom.',409)
            except RuntimeError as exc:return fail(exc,503)
            with sqlite3.connect(d.DB_FILE,timeout=8) as conn:
                cur=conn.execute('''UPDATE token_launches SET status='pending_shares',
                     finalize_tx_b64='',prepared_at=0
                     WHERE id=? AND wallet=? AND status='finalize_prepared'
                     AND finalize_signature='' ''',(launch_id,wallet))
                if cur.rowcount!=1:return fail('Fee-sharing request changed; reload.',409)
            row=lookup(launch_id,wallet)
        if row['reward_mode']!='community' or row['status']!='pending_shares':
            return fail('Launch must be confirmed before finalizing fee shares',409)
        try:built=build_tx(row,'finalize')
        except RuntimeError as exc:return fail(exc,503)
        with sqlite3.connect(d.DB_FILE) as conn:
            cur=conn.execute('''UPDATE token_launches SET finalize_tx_b64=?,
                 status='finalize_prepared', prepared_at=? WHERE id=? AND wallet=?
                 AND status='pending_shares' ''',
                 (built['transaction_b64'],int(time.time()),launch_id,wallet))
            if cur.rowcount!=1:return fail('Another finalize request is in progress',409)
        return jsonify(ok=True,mint=row['mint'],transaction_b64=built['transaction_b64'],expires_in=100)

    @app.post('/api/token-launch/<launch_id>/claim/prepare')
    @d.rate_limit(3,60)
    def prepare_reward_claim(launch_id):
        wallet=identity()
        if not wallet:return fail('Connect your wallet',401)
        if not csrf():return fail('CSRF validation failed',403)
        if not enabled():return fail('Reward claims remain in preflight; no wallet transaction can be prepared',503)
        row=lookup(launch_id,wallet)
        if not row:return fail('Launch not found',404)
        if row['status']!='live' or row['reward_mode']=='holder':
            return fail('Only confirmed creator/community launches can claim creator fees',409)
        with closing(sqlite3.connect(d.DB_FILE)) as conn:
            conn.row_factory=sqlite3.Row
            pending=conn.execute('''SELECT * FROM token_reward_claims
                  WHERE wallet=? AND quote_asset=? AND status IN ('prepared','submitted')
                  ORDER BY created_at DESC LIMIT 1''',(wallet,row['quote_asset'])).fetchone()
        if pending:
            if (pending['launch_id']==launch_id and pending['status']=='prepared'
                    and not pending['signature']):
                try:
                    fresh=(time.time()-pending['created_at']<45
                           or blockhash_valid(pending['transaction_b64']))
                except RuntimeError as exc:return fail(exc,503)
                if fresh:
                    return jsonify(ok=True,claim_id=pending['id'],reused=True,
                      transaction_b64=pending['transaction_b64'],
                      quote_asset=row['quote_asset'],accrued_raw=pending['accrued_raw'],
                      accrued_scope=pending['accrued_scope'])
                # No signature was recorded and the old blockhash has expired;
                # the earlier transaction can no longer settle. Never report
                # it as a successful claim or invent a received amount.
                with sqlite3.connect(d.DB_FILE) as conn:
                    cur=conn.execute('''UPDATE token_reward_claims
                        SET status='expired_unverified' WHERE id=? AND wallet=?
                        AND status='prepared' AND signature='' ''',
                        (pending['id'],wallet))
                    if cur.rowcount!=1:return fail('Claim status changed; reload history.',409)
            else:
                return fail('An earlier claim for this quote asset is awaiting confirmation. Check claim history first.',409)
        block=rpc('getLatestBlockhash',[{'commitment':'confirmed'}])
        blockhash=((block or {}).get('value') or {}).get('blockhash')
        if not blockhash:return fail('No recent Solana blockhash',503)
        path=os.path.join(d.BASE,'pump_adapter','build-reward-claim.cjs')
        params={'wallet':wallet,'mint':row['mint'],'quote_asset':row['quote_asset'],
                'reward_mode':row['reward_mode'],'blockhash':blockhash}
        endpoint=getattr(d,'SOLANA_RPC_URL','') or d.SOLANA_RPC
        try:
            r=subprocess.run(['node',path],input=json.dumps(params),text=True,
                capture_output=True,timeout=14,cwd=os.path.dirname(path),
                env=dict(os.environ,ORCA_LAUNCH_RPC=endpoint))
            if r.returncode or not r.stdout:
                return fail('Creator fees could not be quoted or claim is not ready. No transaction was sent.',503)
            built=json.loads(r.stdout)
            if (built.get('mint')!=row['mint'] or
                    built.get('quote_mint') != (USDC_MINT if row['quote_asset']=='USDC' else WSOL_MINT)
                    or not built.get('transaction_b64') or built.get('transaction_bytes',0)>1232):
                return fail('Reward builder returned inconsistent transaction',503)
            accrued=str(int(built.get('accrued_raw') or 0))
            if int(accrued)<=0:return fail('No creator fees have accrued yet',409)
            claim_id=secrets.token_hex(16)
            with sqlite3.connect(d.DB_FILE) as conn:
                conn.execute('''INSERT INTO token_reward_claims
                  (id,launch_id,wallet,mint,quote_asset,reward_mode,accrued_raw,accrued_scope,
                   transaction_b64,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                  (claim_id,launch_id,wallet,row['mint'],row['quote_asset'],
                   row['reward_mode'],accrued,built.get('accrued_scope',''),
                   built['transaction_b64'],int(time.time())))
        except (OSError,subprocess.TimeoutExpired,ValueError) as exc:
            return fail('Reward claim builder unavailable; nothing has been spent.',503)
        return jsonify(ok=True,claim_id=claim_id,transaction_b64=built['transaction_b64'],
              quote_asset=row['quote_asset'],accrued_raw=accrued,
              accrued_scope=built.get('accrued_scope',''))

    @app.post('/api/token-launch/<launch_id>/claim/confirm')
    @d.rate_limit(8,60)
    def confirm_reward_claim(launch_id):
        wallet=identity()
        if not wallet:return fail('Connect your wallet',401)
        if not csrf():return fail('CSRF validation failed',403)
        body=request.get_json(silent=True)
        if not isinstance(body,dict):return fail('Invalid claim confirmation')
        claim_id=body.get('claim_id','');sig=body.get('signature','')
        if not isinstance(claim_id,str) or not _DRAFT_ID.fullmatch(claim_id):
            return fail('Invalid claim ID')
        row=lookup(launch_id,wallet)
        if not row:return fail('Launch not found',404)
        with closing(sqlite3.connect(d.DB_FILE)) as conn:
            conn.row_factory=sqlite3.Row
            claim=conn.execute('SELECT * FROM token_reward_claims WHERE id=? AND launch_id=? AND wallet=?',
                               (claim_id,launch_id,wallet)).fetchone()
        if not claim:return fail('Claim not found',404)
        if claim['signature'] and claim['signature']!=sig:
            return fail('Claim already recorded with another transaction',409)
        if claim['status']=='confirmed':return jsonify(ok=True,confirmed=True,signature=sig)
        if claim['status'] not in ('prepared','submitted'):
            return fail('Claim is not pending',409)
        try:
            exact={'prepare_tx_b64':claim['transaction_b64'],'wallet':wallet,'mint':row['mint']}
            confirmed=check_signature(sig,exact,'claim')
        except ValueError as exc:return fail(exc)
        except RuntimeError as exc:return fail(exc,503)
        status='confirmed' if confirmed else 'submitted'
        with sqlite3.connect(d.DB_FILE) as conn:
            cur=conn.execute('''UPDATE token_reward_claims
                 SET signature=?,status=?,confirmed_at=?
                 WHERE id=? AND wallet=? AND status IN ('prepared','submitted')
                 AND (signature='' OR signature=?)''',
                 (sig,status,int(time.time()) if confirmed else 0,claim_id,wallet,sig))
            if cur.rowcount!=1:return fail('Claim changed during verification',409)
        return jsonify(ok=True,confirmed=confirmed,signature=sig,status=status), (200 if confirmed else 202)

    @app.get('/api/token-launch/<launch_id>/claims')
    @d.rate_limit(25,60)
    def reward_claim_history(launch_id):
        wallet=identity()
        if not wallet:return fail('Connect your wallet',401)
        row=lookup(launch_id,wallet)
        if not row:return fail('Launch not found',404)
        with closing(sqlite3.connect(d.DB_FILE)) as conn:
            claims=conn.execute('''SELECT id,quote_asset,accrued_raw,accrued_scope,
                             signature,status,created_at,confirmed_at
                    FROM token_reward_claims WHERE launch_id=? AND wallet=?
                    ORDER BY created_at DESC LIMIT 30''',(launch_id,wallet)).fetchall()
        return jsonify(ok=True,claims=[dict(zip(('id','quote_asset','accrued_raw',
                     'accrued_scope','signature','status','created_at','confirmed_at'),v)) for v in claims])

    @app.post('/api/token-launch/<launch_id>/confirm')
    @d.rate_limit(15,60)
    def confirm_launch(launch_id):
        wallet=identity()
        if not wallet:return fail('Connect your wallet',401)
        if not csrf():return fail('CSRF validation failed',403)
        row=lookup(launch_id,wallet)
        if not row:return fail('Launch not found',404)
        body=request.get_json(silent=True)
        if not isinstance(body,dict):return fail('Invalid confirmation')
        stage=body.get('stage'); signature=body.get('signature')
        is_create=stage=='create'
        if stage not in ('create','finalize'):
            return fail('Invalid confirmation stage')
        good_status=('prepared','submitted') if is_create else ('finalize_prepared','finalize_submitted')
        already=('pending_shares','live') if is_create else ('live',)
        if row['status'] in already:
            if signature==(row['launch_signature'] if is_create else row['finalize_signature']):
                return jsonify(ok=True,confirmed=True,draft=public_row(row))
            return fail('A different transaction has already been recorded',409)
        if row['status'] not in good_status:
            return fail('No matching transaction is pending',409)
        sig_col='launch_signature' if is_create else 'finalize_signature'
        if row[sig_col] and row[sig_col]!=signature:
            return fail('Check your original transaction before retrying',409)
        try:
            if not isinstance(signature,str) or not _SIG.fullmatch(signature):
                raise ValueError('Invalid Solana transaction signature')
            confirmed=check_signature(signature,row,stage)
        except ValueError as exc:return fail(exc)
        except RuntimeError as exc:return fail(exc,503)
        if confirmed:
            try:
                if is_create and not mint_exists(row['mint']):
                    return fail('Mint was not verified on Pump. Check explorer before retrying.',503)
                if not is_create and not sharing_check(row['mint'],wallet,
                       row['community_wallet'],row['community_bps']):
                    return fail('On-chain fee shares do not match the agreed split.',409)
            except RuntimeError as exc:return fail(exc,503)
        if is_create:
            status=('pending_shares' if row['reward_mode']=='community' else 'live') if confirmed else 'submitted'
        else:
            status='live' if confirmed else 'finalize_submitted'
        with sqlite3.connect(d.DB_FILE) as conn:
            cur=conn.execute(f'''UPDATE token_launches SET {sig_col}=?, status=?,
                       finalized_at=CASE WHEN ?='live' THEN ? ELSE finalized_at END
                       WHERE id=? AND wallet=? AND status IN ({','.join('?' for _ in good_status)})
                       AND ({sig_col}='' OR {sig_col}=?)''',
                       (signature,status,status,int(time.time()),launch_id,wallet,*good_status,signature))
            if cur.rowcount!=1:return fail('Launch status changed. Reload and check.',409)
        return jsonify(ok=True,confirmed=confirmed,draft=public_row(lookup(launch_id,wallet))), (200 if confirmed else 202)
