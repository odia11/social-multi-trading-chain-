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
import sys
import time
from contextlib import closing
from PIL import Image, ImageOps
from solders.pubkey import Pubkey
from solders.transaction import Transaction as SolanaTransaction
import requests
from flask import abort, jsonify, request, make_response, redirect

USDC_MINT='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
SPL_TOKEN_PROGRAM='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
ASSOCIATED_TOKEN_PROGRAM='ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL'
COMPUTE_BUDGET_PROGRAM='ComputeBudget111111111111111111111111111111'
PHANTOM_CLAIM_WRAPPER='L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95'
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
            received_raw TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(launch_id) REFERENCES token_launches(id)
        )''')
        # Older production DBs predate real received-amount tracking. Empty
        # means unverified, not zero and never the pre-claim snapshot.
        if 'received_raw' not in {r[1] for r in conn.execute('PRAGMA table_info(token_reward_claims)')}:
            try:conn.execute("ALTER TABLE token_reward_claims ADD COLUMN received_raw TEXT NOT NULL DEFAULT ''")
            except sqlite3.OperationalError as exc:
                if 'duplicate column name' not in str(exc).lower():raise
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

    def pilot_wallet(wallet=None):
        w=wallet or identity()
        return (os.getenv('ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED','0')!='1'
            and os.getenv('ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_ENABLED','0')=='1'
            and bool(w) and w in {x.strip() for x in
                os.getenv('ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_WALLETS','').split(',') if x.strip()})

    # Fixed pilot ceilings. The 2 USDC test trade is a SEPARATE wallet action;
    # the token launch NEVER debits a wallet's USDC or buys a token by itself.
    PILOT_MAX_SOL_LAMPORTS=30_000_000
    PILOT_MAX_LAUNCH_SOL_LAMPORTS=25_000_000  # Keep >=0.005 SOL for the test trade/claim
    PILOT_MAX_FOLLOWUP_SOL_LAMPORTS=5_000_000
    PILOT_MAX_TRADE_USDC_MICRO=2_000_000
    PUBLIC_MAX_LAUNCH_SOL_LAMPORTS=50_000_000  # 0.05 SOL hard cap for one launch transaction

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

    # A fixed public RPC fallback covers narrow, READ-ONLY verification,
    # launch simulation and creator-USDC claim preflight methods. It is never used to sign, send or
    # authorize any action, nor to bypass the pilot's simulated cost ceiling.
    # Signed transactions must match the stored message and every signature.
    _VERIFY_RPC='https://solana-rpc.publicnode.com'
    # A 429 is a provider quota, not a reason to hammer the same endpoint
    # three more times for every launch simulation method in one request.
    rpc_throttled_until={}

    def rpc(method,params,*,verification=False,claim_read=False,launch_read=False):
        # All launch preflight calls are read-only. A dedicated RPC can be
        # configured without changing the RPC used by the rest of OrcAgent.
        primary=(os.getenv('ORCA_LAUNCH_RPC','') if launch_read else '') or (getattr(d,'SOLANA_RPC_URL','') or d.SOLANA_RPC)
        if verification and method not in ('getTransaction','getAccountInfo','getSignaturesForAddress'):
            raise RuntimeError('This RPC method is not permitted on the verification fallback')
        if claim_read and (verification or launch_read or method not in (
                'getLatestBlockhash','getBalance','getFeeForMessage',
                'simulateTransaction','isBlockhashValid')):
            raise RuntimeError('This RPC method is not permitted in claim preflight')
        if launch_read and (verification or method not in (
                'getLatestBlockhash','getBalance','getFeeForMessage',
                'simulateTransaction','isBlockhashValid')):
            raise RuntimeError('This RPC method is not permitted in launch preflight')
        can_fallback=verification or claim_read or launch_read
        # The history lookup required for a pending creator claim is
        # especially likely to be blocked by the primary free/indexed RPC.
        # Prefer the independently verified fixed public endpoint first.
        claim_endpoints=list(getattr(d,'CLAIM_SOL_RPCS',[]) or [])
        if claim_read:
            endpoints=list(dict.fromkeys([*claim_endpoints,primary,_VERIFY_RPC]))
        elif verification and method=='getSignaturesForAddress':
            # Indexed account history may be unavailable from public nodes.
            endpoints=list(dict.fromkeys([*claim_endpoints,_VERIFY_RPC,primary]))
        else:
            endpoints=[primary]
        if can_fallback and _VERIFY_RPC not in endpoints:
            endpoints.append(_VERIFY_RPC)
        # If both the configured endpoint and PublicNode are throttled, the
        # official public endpoint is a final read-only launch preflight option.
        # Never route signing/broadcast through a fallback.
        if (launch_read or claim_read) and 'https://api.mainnet-beta.solana.com' not in endpoints:
            endpoints.append('https://api.mainnet-beta.solana.com')
        last_error=None
        throttled_message=('Solana RPC is busy (429). No claim transaction was sent. Retry shortly.'
                           if claim_read else 'Solana RPC is rate-limited (429). Your saved launch is preserved. Check Phantom history before approving again.')
        for number,endpoint in enumerate(endpoints):
            if rpc_throttled_until.get(endpoint,0)>time.monotonic():
                last_error=throttled_message
                continue
            for attempt in range(1 if claim_read else (3 if number==0 else 2)):
                try:
                    response=requests.post(endpoint,json={'jsonrpc':'2.0','id':1,
                         'method':method,'params':params},timeout=9)
                    if response.status_code==429:
                        last_error=throttled_message
                        if attempt < (0 if claim_read else (2 if number==0 else 1)):
                            time.sleep(0.35*(attempt+1))
                            continue
                        rpc_throttled_until[endpoint]=time.monotonic()+12
                        break
                    response.raise_for_status()
                    decoded=response.json()
                    if not isinstance(decoded,dict):
                        raise ValueError('Invalid RPC reply')
                    error=decoded.get('error')
                    if error:
                        if isinstance(error,dict) and error.get('code')==429:
                            last_error=throttled_message
                            if attempt < (0 if claim_read else (2 if number==0 else 1)):
                                time.sleep(0.35*(attempt+1))
                                continue
                            rpc_throttled_until[endpoint]=time.monotonic()+12
                            break
                        raise RuntimeError('Solana RPC rejected '+method)
                    result=decoded.get('result')
                    # A lagging RPC node often returns null for a confirmed
                    # transaction while Pump and other nodes already index it.
                    if result is None and verification and number==0 and len(endpoints)>1:
                        break
                    return result
                except (requests.RequestException,ValueError) as exc:
                    last_error='Solana RPC could not verify this action. Keep the existing token and retry later.'
                    if can_fallback and number<len(endpoints)-1:
                        break
                    raise RuntimeError(last_error) from exc
        raise RuntimeError(last_error or 'Solana RPC verification unavailable. Never create a duplicate token.')

    def build_tx(row,stage):
        # Fail fast when all RPCs are throttled, before potentially spending
        # 90 seconds grinding an Orc mint. Fetch a NEW blockhash after grinding.
        if stage=='create':
            rpc('getLatestBlockhash',[{'commitment':'confirmed'}],launch_read=True)
        mint_secret=None
        if stage=='create':
            try:
                found=subprocess.run([sys.executable,os.path.join(d.BASE,'pump_adapter','grind-mint.py')],
                    text=True,capture_output=True,timeout=96,check=False)
            except (OSError,subprocess.TimeoutExpired) as exc:
                raise RuntimeError('Orc mint address generator unavailable; please retry') from exc
            if found.returncode:
                # Only two fixed, known generator messages are safe to show.
                # Never expose stderr that could contain an ephemeral mint key.
                detail=found.stderr.strip()
                if detail.startswith('Two orc addresses are being prepared.'):
                    raise RuntimeError('Two tokens are already being prepared. Wait a moment and retry; no transaction was sent.')
                if detail.startswith('Finding an orc address took too long.'):
                    raise RuntimeError('The orc address search took too long. Retry this same draft; no token was created.')
                raise RuntimeError('An orc mint address is not ready. Please retry shortly; nothing was sent.')
            mint_secret=found.stdout.strip()
        # Fetch AFTER grinding, so address generation cannot age the blockhash.
        block=rpc('getLatestBlockhash',[{'commitment':'confirmed'}],launch_read=True)
        blockhash=((block or {}).get('value') or {}).get('blockhash')
        if not blockhash:raise RuntimeError('No recent Solana blockhash')
        data={k:row[k] for k in ('wallet','name','symbol','reward_mode',
                                  'quote_asset','community_wallet','community_bps')}
        data.update(stage=stage,blockhash=blockhash,mint=row['mint'],
                    uri='https://orcagent.fun/token-launch/metadata/'+row['id'])
        if mint_secret:data['mint_secret']=mint_secret
        path=os.path.join(d.BASE,'pump_adapter','build-launch.cjs')
        try:
            r=subprocess.run(['/bin/bash',os.path.join(d.BASE,'pump_adapter','run-node.sh'),path],input=json.dumps(data),text=True,
                capture_output=True,timeout=14,cwd=os.path.join(d.BASE,'pump_adapter'),
                check=False)
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise RuntimeError('Token builder unavailable') from exc
        if r.returncode or not r.stdout:
            raise RuntimeError('Token builder rejected this configuration. No transaction was sent.')
        built=json.loads(r.stdout)
        if stage=='create' and not str(built.get('mint','')).endswith('orc'):
            raise RuntimeError('Token builder returned an invalid OrcAgent mint address')
        if built.get('quote_mint') != (USDC_MINT if row['quote_asset']=='USDC' else WSOL_MINT):
            raise RuntimeError('Token builder returned the wrong trading currency')
        if stage=='finalize' and built.get('mint')!=row['mint']:
            raise RuntimeError('Token builder returned the wrong token')
        if not built.get('transaction_b64') or built.get('transaction_bytes',0)>1232:
            raise RuntimeError('Invalid Solana transaction')
        return built

    def pilot_sol_preflight(row,transaction_b64,max_lamports=PILOT_MAX_LAUNCH_SOL_LAMPORTS,*,claim_read=False,enforce_public=False):
        """Read-only simulation; reject if real network/rent cost is unknown.

        Simulated fee-payer balance delta plus getFeeForMessage (conservatively
        counted even if the simulation has already debited the base fee) must
        stay under this pilot's 0.03 SOL limit. This guard is NOT an automatic
        authorization to trade 2 USDC or a guarantee of future network fees.
        """
        if not pilot_wallet(row['wallet']) and not enforce_public:return None
        try:
            raw=base64.b64decode(transaction_b64,validate=True)
            prepared=SolanaTransaction.from_bytes(raw)
            encoded=base64.b64encode(bytes(prepared.message)).decode('ascii')
            wallet=row['wallet']
            balance=rpc('getBalance',[wallet,{'commitment':'confirmed'}],claim_read=claim_read,launch_read=not claim_read)
            before=(balance or {}).get('value')
            fee_result=rpc('getFeeForMessage',[encoded,{'commitment':'confirmed'}],claim_read=claim_read,launch_read=not claim_read)
            fee=(fee_result or {}).get('value')
            simulated=rpc('simulateTransaction',[
                transaction_b64,{'encoding':'base64','commitment':'confirmed',
                'sigVerify':False,
                'accounts':{'encoding':'base64','addresses':[wallet]}}],claim_read=claim_read,launch_read=not claim_read)
            if not isinstance(before,int) or not isinstance(fee,int) or fee<0:
                raise RuntimeError('Pilot network fee/balance unavailable; no transaction prepared')
            outcome=(simulated or {}).get('value') or {}
            accounts=outcome.get('accounts') or []
            if outcome.get('err') is not None:
                logs=outcome.get('logs')
                insufficient=(outcome.get('err') in ('InsufficientFundsForFee','AccountNotFound') or
                    (isinstance(logs,list) and any(isinstance(line,str) and
                     re.search(r'(?:Transfer:\s*)?insufficient\s+(?:lamports|funds|balance)\b',line,re.IGNORECASE)
                     for line in logs)))
                if insufficient:
                    # Do not quote a partial instruction's shortage as the full
                    # launch price. Never expose arbitrary RPC logs to the UI.
                    if claim_read:
                        raise RuntimeError('Insufficient SOL for the creator USDC receiving account rent and claim fees '
                            f'(Phantom balance: {before/1_000_000_000:.9f} SOL). '
                            'Add SOL to this wallet, then retry. No transaction was sent.')
                    raise RuntimeError('Insufficient SOL in Phantom '
                        f'(balance: {before/1_000_000_000:.9f} SOL). '
                        'Add SOL or use Fund launch with USDC on this saved draft '
                        '(if Jupiter offers gasless). Full transaction cost is not yet known. '
                        'No transaction was sent.')
                raise RuntimeError('Pilot transaction simulation failed; no wallet approval is possible')
            if len(accounts)!=1 or not isinstance(accounts[0],dict):
                raise RuntimeError('Pilot fee-payer simulation unavailable; transaction blocked')
            after=accounts[0].get('lamports')
            if not isinstance(after,int) or after<0:
                raise RuntimeError('Pilot simulated SOL balance unavailable; transaction blocked')
            # Never treat apparent SOL gains as a reason to ignore the base fee.
            cost=max(0,before-after)+fee
            if cost<=0 or cost>max_lamports:
                raise RuntimeError('Pilot transaction exceeds its SOL budget; no wallet transaction prepared')
            if before<cost:
                raise RuntimeError('Pilot wallet has insufficient SOL for simulated costs')
            return cost
        except (ValueError,base64.binascii.Error,IndexError,TypeError) as exc:
            raise RuntimeError('Pilot transaction could not be simulated safely') from exc

    def blockhash_valid(transaction_b64,*,claim_read=False):
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
        answer=rpc('isBlockhashValid',[blockhash,{'commitment':'confirmed'}],claim_read=claim_read,launch_read=not claim_read)
        if not isinstance(answer,dict) or not isinstance(answer.get('value'),bool):
            raise RuntimeError('Solana blockhash validity unavailable')
        return answer['value']

    def sharing_check(mint,wallet,community,bps):
        helper=os.path.join(d.BASE,'pump_adapter','check-sharing.cjs')
        def run(data):
            try:
                p=subprocess.run(['/bin/bash',os.path.join(d.BASE,'pump_adapter','run-node.sh'),helper],input=json.dumps(data),text=True,
                    capture_output=True,timeout=7,cwd=os.path.dirname(helper))
                if p.returncode:raise RuntimeError('Share configuration could not be verified')
                return json.loads(p.stdout)
            except (OSError,subprocess.TimeoutExpired,ValueError) as exc:
                raise RuntimeError('Share configuration could not be verified') from exc
        info=run({'action':'address','mint':mint})
        account=rpc('getAccountInfo',[info['address'],{'encoding':'base64','commitment':'confirmed'}],verification=True)
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
        info=rpc('getAccountInfo',[str(pda),{'encoding':'base64','commitment':'confirmed'}],verification=True)
        return bool((info or {}).get('value') and info['value'].get('owner')==PUMP_PROGRAM)

    def _claim_instructions_match(signed_msg,prepared_msg,wallet):
        """Allow ONLY the wallet wrapper observed around this precise claim.

        Phantom may insert two standard compute-budget instructions and two
        L2TEx wallet-envelope instructions. Pump's original claim instructions
        must remain IDENTICAL in program ID, ordered account PUBKEYS and data.
        Unknown inserted instructions, changed fee payer or altered account
        lists are rejected. Never use this exception for creating tokens or
        changing irreversible community sharing configuration.
        """
        def instructions(msg):
            keys=msg.account_keys
            return [(str(keys[ix.program_id_index]),
                     tuple(str(keys[index]) for index in ix.accounts),
                     bytes(ix.data)) for ix in msg.instructions]
        expected=instructions(prepared_msg)
        actual=instructions(signed_msg)
        if actual==expected:return True
        if str(signed_msg.account_keys[0])!=wallet:return False
        i=0
        while i<len(actual) and actual[i][0]==COMPUTE_BUDGET_PROGRAM and i<2:
            program,accounts,data=actual[i]
            if accounts or not ((len(data)==5 and data[:1]==b'\x02')
                 or (len(data)==9 and data[:1]==b'\x03')):
                return False
            # Reject arbitrary compute limits and prices. The final wallet
            # charge is also bounded using actual confirmed payer balances.
            if data[0]==2 and not 1<=int.from_bytes(data[1:],'little')<=1_400_000:
                return False
            if data[0]==3 and int.from_bytes(data[1:],'little')>100_000_000:
                return False
            i+=1
        if actual[i:i+len(expected)]!=expected:return False
        tail=actual[i+len(expected):]
        if not tail:return True
        if len(tail)!=2 or any(item[0]!=PHANTOM_CLAIM_WRAPPER for item in tail):
            return False
        owner=Pubkey.from_string(wallet)
        ata,_=Pubkey.find_program_address([
            bytes(owner),bytes(Pubkey.from_string(SPL_TOKEN_PROGRAM)),
            bytes(Pubkey.from_string(USDC_MINT))],
            Pubkey.from_string(ASSOCIATED_TOKEN_PROGRAM))
        return (tail[0][1]==(wallet,) and tail[1][1]==(str(ata),)
                and all(0<len(item[2])<=64 for item in tail))

    # Internal offline/on-chain regression hook, never an HTTP route.
    app._orca_claim_message_match=_claim_instructions_match

    def check_signature(signature,row,stage):
        """Check the *exact* prepared transaction, not merely any Pump trade.

        A user-supplied signature for some other swap involving the same mint
        must never mark a token launched or a fee split finalized. The two
        signed messages must match byte-for-byte; RPC confirmed transaction
        and the creator's wallet signature prove this was the agreed action.
        """
        if not isinstance(signature,str) or not _SIG.fullmatch(signature):
            raise ValueError('Invalid transaction signature')
        stored=(row['prepare_tx_b64'] if stage in ('create','claim')
                else row['finalize_tx_b64'])
        if not stored:raise ValueError('No prepared transaction for this action')
        result=rpc('getTransaction',[signature,{'encoding':'base64',
                         'commitment':'confirmed','maxSupportedTransactionVersion':0}],verification=True)
        if not result:return False
        if (result.get('meta') or {}).get('err') is not None:
            raise ValueError('The Solana transaction failed')
        try:
            raw=result['transaction'][0]
            signed=SolanaTransaction.from_bytes(base64.b64decode(raw,validate=True))
            prepared=SolanaTransaction.from_bytes(base64.b64decode(stored,validate=True))
            if bytes(signed.message)!=bytes(prepared.message):
                if stage!='claim' or not _claim_instructions_match(
                         signed.message,prepared.message,row['wallet']):
                    raise ValueError('Signed transaction does not match this launch')
                # Verify the TOTAL actual SOL debit, not a quoted estimate.
                payer_before=(result.get('meta') or {}).get('preBalances') or []
                payer_after=(result.get('meta') or {}).get('postBalances') or []
                if not (payer_before and payer_after and
                        type(payer_before[0]) is int and type(payer_after[0]) is int and
                        0<payer_before[0]-payer_after[0]<=PILOT_MAX_FOLLOWUP_SOL_LAMPORTS):
                    raise ValueError('Modified claim exceeded the permitted SOL debit')
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

    def verified_creator_usdc_receipt(signature,wallet,*,allow_zero=False):
        """Actual received USDC in the creator's canonical ATA in this TX.

        Compare pre/post balances of the exact recipient token account in the
        confirmed transaction, never the fee vault snapshot or a wallet-wide
        balance observed at another time. No broadcast and no secret access.
        """
        owner=Pubkey.from_string(wallet)
        ata,_=Pubkey.find_program_address([
            bytes(owner),bytes(Pubkey.from_string(SPL_TOKEN_PROGRAM)),
            bytes(Pubkey.from_string(USDC_MINT))],
            Pubkey.from_string(ASSOCIATED_TOKEN_PROGRAM))
        result=rpc('getTransaction',[signature,{'encoding':'json',
                      'commitment':'confirmed','maxSupportedTransactionVersion':0}],verification=True)
        if not result or (result.get('meta') or {}).get('err') is not None:
            raise RuntimeError('Creator USDC claim receipt is not yet verifiable')
        try:
            keys=result['transaction']['message']['accountKeys']
            idx=keys.index(str(ata))
            meta=result['meta']
            def amount(which):
                for entry in meta[which]:
                    if entry.get('accountIndex')!=idx:continue
                    if (entry.get('mint')!=USDC_MINT or entry.get('owner')!=wallet
                            or entry.get('uiTokenAmount',{}).get('decimals')!=6):
                        raise ValueError('Unverifiable USDC recipient account')
                    number=entry['uiTokenAmount']['amount']
                    if not isinstance(number,str) or not number.isdecimal():raise ValueError
                    return int(number)
                return None
            before=amount('preTokenBalances')
            after=amount('postTokenBalances')
            if after is None or (before is not None and after<before):raise ValueError
            if before is None:
                # No preTokenBalance can mean the ATA was created by this
                # claim, but must not mean missing metadata for an EXISTING
                # wallet balance; that would falsely credit the full balance.
                lamports=meta.get('preBalances')
                if (not isinstance(lamports,list) or idx>=len(lamports)
                        or lamports[idx]!=0):
                    raise ValueError('New recipient account was not verifiable')
            received=after-(before or 0)
            if received<0 or (received==0 and not allow_zero):
                raise ValueError('No verified USDC was received')
            return str(received)
        except (KeyError,ValueError,IndexError,TypeError,AttributeError) as exc:
            raise RuntimeError('Confirmed USDC recipient delta unavailable; retry claim confirmation') from exc

    def reconcile_reward_claims(wallet_filter=None):
        '''Recover on-chain creator rewards when Phantom changed tx wrappers.

        A wallet may return a signature but the client can be suspended before
        OrcAgent saves it, or strict legacy message comparison can reject it.
        Search only the originating wallet's already-confirmed transactions
        near each locally prepared claim, verify the exact original Pump core,
        every signer, actual SOL costs and actual USDC recipient delta.
        No signing, sending, new claim creation or arbitrary wallet credit.
        '''
        with closing(sqlite3.connect(d.DB_FILE)) as conn:
            conn.row_factory=sqlite3.Row
            query='''SELECT * FROM token_reward_claims
                WHERE status IN ('prepared','submitted','expired_unverified') AND reward_mode='creator'
                AND quote_asset='USDC' AND created_at>?'''
            params=[int(time.time())-7*86400]
            if wallet_filter:
                query+=' AND wallet=?'
                params.append(wallet_filter)
            rows=conn.execute(query+' ORDER BY created_at ASC LIMIT 30',params).fetchall()
        if not rows:return {'checked':0,'recovered':0,'no_payout':0,'unavailable':0}
        wallet_history={};recovered=no_payout=unavailable=0
        for source in rows:
            claim=dict(source);wallet=claim['wallet']
            if wallet not in wallet_history:
                try:
                    found=rpc('getSignaturesForAddress',
                        [wallet,{'limit':100}],verification=True)
                    wallet_history[wallet]=found if isinstance(found,list) else []
                except RuntimeError:
                    unavailable+=1
                    wallet_history[wallet]=[]
            # The oldest transaction at/after the local quote belongs to the
            # earliest pending record. No newer claim can adopt an earlier tx.
            candidates=sorted(wallet_history[wallet],
                 key=lambda x:x.get('blockTime') or 0)
            for tx in candidates:
                timestamp=tx.get('blockTime');signature=tx.get('signature')
                if (not isinstance(timestamp,int) or tx.get('err') is not None
                    or not isinstance(signature,str) or not _SIG.fullmatch(signature)
                    or not claim['created_at']-5<=timestamp<=claim['created_at']+180):
                    continue
                with closing(sqlite3.connect(d.DB_FILE)) as conn:
                    already=conn.execute('''SELECT id FROM token_reward_claims
                        WHERE wallet=? AND signature=? AND id<>? LIMIT 1''',
                        (wallet,signature,claim['id'])).fetchone()
                if already:continue
                exact={'prepare_tx_b64':claim['transaction_b64'],
                       'wallet':wallet,'mint':claim['mint']}
                try:
                    if not check_signature(signature,exact,'claim'):continue
                    received_raw=verified_creator_usdc_receipt(
                                      signature,wallet,allow_zero=True)
                except (RuntimeError,ValueError,KeyError,TypeError):
                    continue
                status='confirmed' if int(received_raw)>0 else 'confirmed_no_payout'
                with sqlite3.connect(d.DB_FILE,timeout=8) as conn:
                    updated=conn.execute('''UPDATE token_reward_claims
                        SET signature=?, status=?, received_raw=?, confirmed_at=?
                        WHERE id=? AND wallet=? AND status IN ('prepared','submitted','expired_unverified')
                        AND (signature='' OR signature=?)''',
                        (signature,status,received_raw,timestamp,claim['id'],wallet,
                         signature))
                    if updated.rowcount:
                        recovered+=int(received_raw)>0
                        no_payout+=int(received_raw)==0
                break
        print('[pump-claim] chain reconciliation checked='+str(len(rows))+
              ' received='+str(recovered)+' no_payout='+str(no_payout)+
              ' unavailable='+str(unavailable),flush=True)
        return {'checked':len(rows),'recovered':recovered,'no_payout':no_payout,
                'unavailable':unavailable}

    app._orca_reconcile_reward_claims=reconcile_reward_claims

    def reconcile_submitted_launches():
        """Recover already signed and recorded Phantom transactions on restart.

        This changes ONLY the database status after exact on-chain verification;
        it never prepares, signs or sends a transaction, nor requires the
        current browser to have the original wallet selected.
        """
        with closing(sqlite3.connect(d.DB_FILE)) as conn:
            conn.row_factory=sqlite3.Row
            rows=conn.execute('''SELECT * FROM token_launches
                       WHERE (status='submitted' AND launch_signature<>''
                                  AND prepare_tx_b64<>'')
                          OR (status='finalize_submitted' AND finalize_signature<>''
                                  AND finalize_tx_b64<>'')
                       ORDER BY created_at ASC LIMIT 50''').fetchall()
        scanned=recovered=unavailable=0
        for raw in rows:
            row=dict(raw)
            stage='create' if row['status']=='submitted' else 'finalize'
            sig=row['launch_signature'] if stage=='create' else row['finalize_signature']
            scanned+=1
            try:
                if not check_signature(sig,row,stage):
                    unavailable+=1
                    continue
                if stage=='create' and not mint_exists(row['mint']):
                    unavailable+=1
                    continue
                if stage=='finalize' and not sharing_check(row['mint'],row['wallet'],
                                            row['community_wallet'],row['community_bps']):
                    unavailable+=1
                    continue
            except (RuntimeError,ValueError,KeyError,TypeError):
                # Preserve status. Do not log RPC data or user-controlled text.
                unavailable+=1
                continue
            target=('pending_shares' if row['reward_mode']=='community' else 'live') if stage=='create' else 'live'
            previous='submitted' if stage=='create' else 'finalize_submitted'
            sig_col='launch_signature' if stage=='create' else 'finalize_signature'
            with sqlite3.connect(d.DB_FILE,timeout=8) as conn:
                change=conn.execute(f'''UPDATE token_launches
                      SET status=?, finalized_at=CASE WHEN ?='live'
                          THEN ? ELSE finalized_at END
                      WHERE id=? AND wallet=? AND mint=? AND status=?
                            AND {sig_col}=?''',
                      (target,target,int(time.time()),row['id'],row['wallet'],
                           row['mint'],previous,sig))
                recovered+=change.rowcount
        # Once signed launches are restored, also reconcile already-broadcast
        # claims. Do not require the owner to reopen Phantom or press Claim.
        reconcile_reward_claims()
        print(f'[pump-launch] chain reconciliation checked={scanned} '
              f'recovered={recovered} still_pending={unavailable}',flush=True)
        return {'checked':scanned,'recovered':recovered,'still_pending':unavailable}

    # Internal callable only, not an HTTP endpoint.
    app._orca_reconcile_submitted_launches=reconcile_submitted_launches

    def launch_assets_version():
        # Bust browser caches for BOTH refreshed pages after deployment.
        names=('token-launch.js','token-launches.js','token-launch-redesign.css')
        return str(max(int(os.stat(os.path.join(d.BASE,'static',name)).st_mtime)
                       for name in names))

    @app.get('/token-launch')
    def token_launch_page():
        wallet=identity()
        if not wallet:return redirect('/?connect=1')
        return d._render_no_cache('token_launch.html',wallet=wallet,
            csrf_token=d._get_csrf_token(),launch_enabled=enabled(),
            pilot_creator_only=pilot_wallet(wallet),
            funding_available=bool(os.getenv('JUPITER_API_KEY','').strip()),
            app_version=launch_assets_version(),
            navbar_html=d._navbar_html)

    @app.get('/api/token-launch/config')
    @d.rate_limit(30,60)
    def launch_config():
        if not identity():return fail('Connect your wallet',401)
        pilot=pilot_wallet()
        return jsonify(ok=True,enabled=enabled(),default_quote='USDC',
           default_reward_mode='creator' if pilot else 'community',
           sol_conversion='separate_wallet_approved_gasless_usdc_swap',pilot_creator_only=pilot,
           public_max_launch_sol_lamports=PUBLIC_MAX_LAUNCH_SOL_LAMPORTS,
           pilot_max_sol_lamports=PILOT_MAX_SOL_LAMPORTS if pilot else None,
           pilot_max_launch_sol_lamports=PILOT_MAX_LAUNCH_SOL_LAMPORTS if pilot else None,
           pilot_max_trade_usdc_micro=PILOT_MAX_TRADE_USDC_MICRO if pilot else None,
           usdc_launch_funding_available=bool(os.getenv('JUPITER_API_KEY','').strip()),
           fee_disclosure='Pump fees and Solana network/rent fees apply. OrcAgent does not charge an extra launch fee.',
           capabilities={'creator':True,'community':not pilot,'holder':not pilot})

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
            if pilot_wallet(wallet) and (mode!='creator' or quote!='USDC'):
                raise ValueError('Pilot allows USDC / 100% Creator Rewards only')
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

    @app.get('/launches')
    @d.rate_limit(45,60)
    def launch_dashboard():
        # Public directory. Only verified/live OrcAgent token launches are
        # listed; wallet drafts, signatures and fee-claim history stay private.
        return d._render_no_cache('token_launches.html',
                 app_version=launch_assets_version(),
                 navbar_html=d._navbar_html)

    @app.get('/api/token-launches')
    @d.rate_limit(30,60)
    def launch_directory():
        query=request.args.get('q','').strip()
        asset=request.args.get('asset','all')
        owner=request.args.get('owner','all')
        page=request.args.get('page','1')
        if len(query)>70 or asset not in ('all','USDC','SOL') or owner not in ('all','mine'):
            return fail('Invalid directory search or filter')
        if not page.isascii() or not page.isdecimal() or not 1<=int(page)<=1000:
            return fail('Invalid directory page')
        wallet=identity()
        if owner=='mine' and not wallet:
            return fail('Connect Phantom to filter your launches',401)
        where=["status='live'", "mint IS NOT NULL", "launch_signature<>''"]
        params=[]
        if asset!='all':where.append('quote_asset=?');params.append(asset)
        if owner=='mine':where.append('wallet=?');params.append(wallet)
        if query:
            term='%'+query.replace(chr(92),chr(92)*2).replace('%',chr(92)+'%').replace('_',chr(92)+'_')+'%'
            where.append("(name LIKE ? ESCAPE char(92) OR symbol LIKE ? ESCAPE char(92) OR mint LIKE ? ESCAPE char(92) OR wallet LIKE ? ESCAPE char(92))")
            params.extend([term]*4)
        clause=' AND '.join(where)
        with closing(sqlite3.connect(d.DB_FILE)) as conn:
            conn.row_factory=sqlite3.Row
            total=conn.execute('SELECT count(*) FROM token_launches WHERE '+clause,params).fetchone()[0]
            # Counts are all confirmed launches, not Pump's market cap or live
            # balances; those values must never be fabricated from drafts.
            stats=conn.execute("SELECT quote_asset,count(*) FROM token_launches WHERE status='live' AND mint IS NOT NULL AND launch_signature<>'' GROUP BY quote_asset").fetchall()
            rows=conn.execute('''SELECT id,name,symbol,description,quote_asset,
                    reward_mode,community_wallet,community_bps,wallet,mint,created_at,finalized_at
                    FROM token_launches WHERE '''+clause+
                    ' ORDER BY finalized_at DESC,created_at DESC,id DESC LIMIT 20 OFFSET ?',
                    [*params,(int(page)-1)*20]).fetchall()
        entries=[]
        for row in rows:
            item=dict(row)
            item['logo_url']='/token-launch/icon/'+item['id']
            item['trade_url']='/live-market?mint='+item['mint']
            entries.append(item)
        response=jsonify(ok=True,launches=entries,total=total,page=int(page),
             page_size=20,counts={r[0]:r[1] for r in stats})
        response.headers['Cache-Control']='private, no-store'
        return response

    @app.post('/api/token-launch/<launch_id>/prepare')
    @d.rate_limit(4,60)
    def prepare_launch(launch_id):
        wallet=identity()
        if not wallet:return fail('Connect your wallet',401)
        if not csrf():return fail('CSRF validation failed',403)
        if not enabled():return fail('Token Launch is in preflight; no mainnet transaction can be prepared',503)
        row=lookup(launch_id,wallet)
        if not row:return fail('Launch not found',404)
        if pilot_wallet(wallet) and (row['reward_mode']!='creator' or row['quote_asset']!='USDC'):
            return fail('Pilot allows USDC / 100% Creator Rewards only',409)
        if pilot_wallet(wallet):
            with closing(sqlite3.connect(d.DB_FILE)) as conn:
                already=conn.execute('''SELECT id FROM token_launches
                   WHERE wallet=? AND id!=? AND (mint IS NOT NULL
                       OR status NOT IN ('draft','cancelled')) LIMIT 1''',
                   (wallet,launch_id)).fetchone()
            if already:return fail('Pilot permits one test token per creator wallet',409)
        if row['status']=='prepared' and not row['launch_signature']:
            # Phantom rejection/suspended mobile app must not permanently
            # strand the creator's unsent token. Return the identical signed
            # mint transaction while its blockhash might still be valid.
            if time.time()-row['prepared_at']<45:
                try:pilot_cost=pilot_sol_preflight(row,row['prepare_tx_b64'],
                    max_lamports=PILOT_MAX_LAUNCH_SOL_LAMPORTS if pilot_wallet(wallet)
                        else PUBLIC_MAX_LAUNCH_SOL_LAMPORTS,enforce_public=True)
                except RuntimeError as exc:return fail(exc,503)
                return jsonify(ok=True,mint=row['mint'],transaction_b64=row['prepare_tx_b64'],
                    quote_asset=row['quote_asset'],reward_mode=row['reward_mode'],
                    needs_finalization=row['reward_mode']=='community',
                    pilot_estimated_max_sol_lamports=pilot_cost,expires_in=60,reused=True)
            try:
                if blockhash_valid(row['prepare_tx_b64']):
                    pilot_cost=pilot_sol_preflight(row,row['prepare_tx_b64'],
                    max_lamports=PILOT_MAX_LAUNCH_SOL_LAMPORTS if pilot_wallet(wallet)
                        else PUBLIC_MAX_LAUNCH_SOL_LAMPORTS,enforce_public=True)
                    return jsonify(ok=True,mint=row['mint'],transaction_b64=row['prepare_tx_b64'],
                        quote_asset=row['quote_asset'],reward_mode=row['reward_mode'],
                        needs_finalization=row['reward_mode']=='community',
                        pilot_estimated_max_sol_lamports=pilot_cost,expires_in=45,reused=True)
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
        # A real mainnet dry run needs ~0.007 SOL for SOL-paired creation and
        # ~0.009 SOL for USDC-paired creation (rent varies). Reject clearly
        # before grinding an ephemeral mint when the fee payer cannot cover a
        # modest 0.01 SOL starting reserve. No user funds move here.
        try:
            starting=rpc('getBalance',[wallet,{'commitment':'confirmed'}],launch_read=True)
            available=(starting or {}).get('value')
            if type(available) is not int or available<0:
                raise RuntimeError('Could not verify your SOL balance. Keep this saved draft and retry later.')
            if available<10_000_000:
                return fail('Insufficient SOL: Phantom has '
                    f'{available/1_000_000_000:.6f} SOL. Keep at least 0.01 SOL '
                    'for creation/rent. Add SOL or use Fund launch with USDC '
                    'on this draft (gasless quote required). No token was created.',409)
            built=build_tx(row,'create')
            pilot_cost=pilot_sol_preflight(row,built['transaction_b64'],
                max_lamports=PILOT_MAX_LAUNCH_SOL_LAMPORTS if pilot_wallet(wallet)
                    else PUBLIC_MAX_LAUNCH_SOL_LAMPORTS,enforce_public=True)
        except RuntimeError as exc:return fail(exc,503)
        with sqlite3.connect(d.DB_FILE,timeout=8) as conn:
            conn.execute('BEGIN IMMEDIATE')
            # An allowlisted wallet must not bypass the one-token pilot by
            # preparing two different drafts concurrently in two browser tabs.
            if pilot_wallet(wallet):
                other=conn.execute('''SELECT id FROM token_launches
                   WHERE wallet=? AND id!=? AND (mint IS NOT NULL
                       OR status NOT IN ('draft','cancelled')) LIMIT 1''',
                   (wallet,launch_id)).fetchone()
                if other:return fail('Pilot permits one test token per creator wallet',409)
            cur=conn.execute('''UPDATE token_launches
                  SET mint=?, prepare_tx_b64=?, status='prepared', prepared_at=?
                  WHERE id=? AND wallet=? AND status='draft' ''',
                  (built['mint'],built['transaction_b64'],int(time.time()),launch_id,wallet))
            if cur.rowcount!=1:return fail('This launch is already being prepared. Reload status.',409)
        return jsonify(ok=True,mint=built['mint'],transaction_b64=built['transaction_b64'],
            quote_asset=row['quote_asset'],reward_mode=row['reward_mode'],
            needs_finalization=built.get('needs_fee_share_finalization',False),
            pilot_estimated_max_sol_lamports=pilot_cost,expires_in=100)

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
                try:followup_cost=pilot_sol_preflight(row,row['finalize_tx_b64'],
                    PUBLIC_MAX_LAUNCH_SOL_LAMPORTS,enforce_public=True)
                except RuntimeError as exc:return fail(exc,503)
                return jsonify(ok=True,mint=row['mint'],
                    transaction_b64=row['finalize_tx_b64'],
                    pilot_estimated_max_sol_lamports=followup_cost,
                    expires_in=60,reused=True)
            try:
                if blockhash_valid(row['finalize_tx_b64']):
                    followup_cost=pilot_sol_preflight(row,row['finalize_tx_b64'],
                        PUBLIC_MAX_LAUNCH_SOL_LAMPORTS,enforce_public=True)
                    return jsonify(ok=True,mint=row['mint'],transaction_b64=row['finalize_tx_b64'],
                        pilot_estimated_max_sol_lamports=followup_cost,
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
        try:
            built=build_tx(row,'finalize')
            followup_cost=pilot_sol_preflight(row,built['transaction_b64'],
                PUBLIC_MAX_LAUNCH_SOL_LAMPORTS,enforce_public=True)
        except RuntimeError as exc:return fail(exc,503)
        with sqlite3.connect(d.DB_FILE) as conn:
            cur=conn.execute('''UPDATE token_launches SET finalize_tx_b64=?,
                 status='finalize_prepared', prepared_at=? WHERE id=? AND wallet=?
                 AND status='pending_shares' ''',
                 (built['transaction_b64'],int(time.time()),launch_id,wallet))
            if cur.rowcount!=1:return fail('Another finalize request is in progress',409)
        return jsonify(ok=True,mint=row['mint'],transaction_b64=built['transaction_b64'],
            pilot_estimated_max_sol_lamports=followup_cost,expires_in=100)

    @app.post('/api/token-launch/<launch_id>/recover-submitted')
    @d.rate_limit(3,60)
    def recover_expired_phantom_launch(launch_id):
        """Recover an unlanded signature, NEVER broadcast/create another mint.

        Wallet owner explicitly requests recovery of the SAME saved draft.
        Independently verify historical signature, finalized blockhash and
        both mint + Pump curve on two mainnet RPCs before clearing the old mint.
        """
        wallet=identity()
        if not wallet:return fail('Connect your wallet',401)
        if not csrf():return fail('CSRF validation failed',403)
        row=lookup(launch_id,wallet)
        if not row:return fail('Launch not found',404)
        if row['status']!='submitted' or not row['launch_signature']:
            return fail('Only an unconfirmed submitted token can be recovered',409)
        try:
            from launch_recovery import prove_expired_unlanded
            allowed,reason=prove_expired_unlanded(row,primary=(
                os.getenv('ORCA_LAUNCH_RPC') or getattr(d,'SOLANA_RPC_URL','')
                or getattr(d,'SOLANA_RPC','')))
        except (ValueError,KeyError,TypeError,IndexError):
            return fail('Could not validate the saved transaction safely. Nothing changed.',503)
        if not allowed:return fail(reason,409)
        with sqlite3.connect(d.DB_FILE,timeout=8) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("""CREATE TABLE IF NOT EXISTS token_launch_recovery_audit(
                id INTEGER PRIMARY KEY AUTOINCREMENT,launch_id TEXT NOT NULL,
                old_mint TEXT NOT NULL,old_signature TEXT NOT NULL,
                recovered_at INTEGER NOT NULL)""")
            update=db.execute("""UPDATE token_launches SET status='draft',
               mint=NULL,prepare_tx_b64='',launch_signature='',prepared_at=0,
               error='Previous signed launch expired unconfirmed; new Phantom approval required'
               WHERE id=? AND wallet=? AND status='submitted'
                 AND launch_signature=? AND mint=?""",
               (launch_id,wallet,row['launch_signature'],row['mint']))
            if update.rowcount!=1:
                db.rollback()
                return fail('Token status changed. Check the existing transaction.',409)
            db.execute("""INSERT INTO token_launch_recovery_audit
                  (launch_id,old_mint,old_signature,recovered_at)
                  VALUES (?,?,?,?)""",
                  (launch_id,row['mint'],row['launch_signature'],int(time.time())))
        return jsonify(ok=True,recovered=True,
            msg='The old transaction expired without a confirmed token. Your original draft is ready for a NEW Phantom approval. No transaction was sent by recovery.')

    @app.get('/api/token-launch/<launch_id>/creator-fees')
    @d.rate_limit(10,60)
    def creator_usdc_fee_status(launch_id):
        wallet=identity()
        if not wallet:return fail('Connect your wallet',401)
        row=lookup(launch_id,wallet)
        if not row:return fail('Launch not found',404)
        if row['status']!='live' or row['reward_mode']!='creator' or row['quote_asset']!='USDC':
            return fail('Confirm your USDC Creator Rewards launch first',409)
        # Pump's creator vault belongs to the WALLET, not to an individual
        # mint; never present its balance as this token's revenue. The PumpSwap
        # AMM vault is separate and is not included in this number.
        creator=Pubkey.from_string(wallet)
        vault,_=Pubkey.find_program_address([b'creator-vault',bytes(creator)],
                      Pubkey.from_string(PUMP_PROGRAM))
        ata,_=Pubkey.find_program_address([
                    bytes(vault),bytes(Pubkey.from_string(SPL_TOKEN_PROGRAM)),
                    bytes(Pubkey.from_string(USDC_MINT))],
                    Pubkey.from_string(ASSOCIATED_TOKEN_PROGRAM))
        try:
            state=rpc('getAccountInfo',[str(ata),{'encoding':'base64',
                     'commitment':'confirmed'}],verification=True)
            account=(state or {}).get('value')
            raw=0
            if account is not None:
                if account.get('owner')!=SPL_TOKEN_PROGRAM:
                    raise RuntimeError('Creator vault returned an unexpected token program')
                data=base64.b64decode(account['data'][0],validate=True)
                if (len(data)<72 or data[:32]!=bytes(Pubkey.from_string(USDC_MINT))
                        or data[32:64]!=bytes(vault)):
                    raise RuntimeError('Creator vault did not match the expected USDC owner')
                raw=int.from_bytes(data[64:72],'little')
        except (KeyError,IndexError,TypeError,ValueError) as exc:
            return fail('USDC creator vault could not be verified safely; retry later',503)
        except RuntimeError as exc:return fail(exc,503)
        response=jsonify(ok=True,quote_asset='USDC',pump_vault_raw=str(raw),
               scope='creator_wallet_all_tokens_pump_bonding_curve',
               note='Wallet-wide unclaimed Pump bonding-curve USDC fees, not token-specific, not yet received, PumpSwap fees excluded.')
        response.headers['Cache-Control']='private, no-store'
        return response

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
        # An on-chain Phantom approval can settle before the client successfully
        # posts its signature. Reconcile BEFORE offering any fresh payable tx.
        if row['reward_mode']=='creator' and row['quote_asset']=='USDC':
            with closing(sqlite3.connect(d.DB_FILE)) as conn:
                unresolved=conn.execute('''SELECT id FROM token_reward_claims
                    WHERE wallet=? AND quote_asset='USDC'
                    AND status IN ('prepared','submitted') LIMIT 1''',
                    (wallet,)).fetchone()
            if unresolved:
                result=reconcile_reward_claims(wallet)
                if result['unavailable']:
                    return fail('Existing creator claim cannot be checked on Solana right now. Do not approve a second payment.',503)
        if pilot_wallet(wallet):
            with closing(sqlite3.connect(d.DB_FILE)) as conn:
                claimed=conn.execute('''SELECT id FROM token_reward_claims
                  WHERE wallet=? AND status='confirmed' LIMIT 1''',(wallet,)).fetchone()
            if claimed:return fail('Private pilot permits only one confirmed reward claim',409)
        with closing(sqlite3.connect(d.DB_FILE)) as conn:
            conn.row_factory=sqlite3.Row
            pending=conn.execute('''SELECT * FROM token_reward_claims
                  WHERE wallet=? AND quote_asset=? AND status IN ('prepared','submitted')
                  ORDER BY created_at DESC LIMIT 1''',(wallet,row['quote_asset'])).fetchone()
        if pending:
            if (pending['launch_id']==launch_id and pending['status']=='prepared'
                    and not pending['signature'] and
                    time.time()-pending['created_at']<120):
                return fail('A recent creator claim may already have been approved in Phantom. Wait two minutes and check Claim history before preparing another transaction.',409)
            if (pending['launch_id']==launch_id and pending['status']=='prepared'
                    and not pending['signature']):
                try:
                    fresh=(time.time()-pending['created_at']<45
                           or blockhash_valid(pending['transaction_b64'],claim_read=(row['reward_mode']=='creator' and row['quote_asset']=='USDC')))
                except RuntimeError as exc:return fail(exc,503)
                if fresh:
                    try:pilot_cost=pilot_sol_preflight(row,pending['transaction_b64'],
                                         PILOT_MAX_FOLLOWUP_SOL_LAMPORTS,claim_read=(row['reward_mode']=='creator' and row['quote_asset']=='USDC'))
                    except RuntimeError as exc:return fail(exc,503)
                    return jsonify(ok=True,claim_id=pending['id'],reused=True,
                      transaction_b64=pending['transaction_b64'],
                      quote_asset=row['quote_asset'],accrued_raw=pending['accrued_raw'],
                      pilot_estimated_max_sol_lamports=pilot_cost,
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
        try:
            block=rpc('getLatestBlockhash',[{'commitment':'confirmed'}],claim_read=(row['reward_mode']=='creator' and row['quote_asset']=='USDC'))
        except RuntimeError as exc:return fail(exc,503)
        blockhash=((block or {}).get('value') or {}).get('blockhash')
        if not blockhash:return fail('No recent Solana blockhash',503)
        path=os.path.join(d.BASE,'pump_adapter','build-reward-claim.cjs')
        params={'wallet':wallet,'mint':row['mint'],'quote_asset':row['quote_asset'],
                'reward_mode':row['reward_mode'],'blockhash':blockhash}
        primary=getattr(d,'SOLANA_RPC_URL','') or d.SOLANA_RPC
        endpoints=([*list(getattr(d,'CLAIM_SOL_RPCS',[]) or []),primary,_VERIFY_RPC,
                    'https://api.mainnet-beta.solana.com']
                   if row['reward_mode']=='creator' and row['quote_asset']=='USDC'
                   else [primary])
        try:
            built=None
            for endpoint in dict.fromkeys(endpoints):
                if rpc_throttled_until.get(endpoint,0)>time.monotonic():
                    continue
                r=subprocess.run(['/bin/bash',os.path.join(d.BASE,'pump_adapter','run-node.sh'),path],input=json.dumps(params),text=True,
                    capture_output=True,timeout=14,cwd=os.path.dirname(path),
                    env=dict(os.environ,ORCA_LAUNCH_RPC=endpoint))
                if r.returncode==0 and r.stdout:
                    built=json.loads(r.stdout)
                    break
                # These are read-only account lookups; rotate only for provider
                # rate limits and outages. Validation/protocol failures are not
                # fixed by another RPC and must never be hidden.
                stderr=(r.stderr or '').lower()
                if not any(marker in stderr for marker in (
                    '429','too many requests','rate limit','fetch failed',
                    'etimedout','econnreset','403','forbidden','unauthorized',
                    '502 bad gateway','503 service unavailable')):
                    return fail('Creator fees could not be quoted or claim is not ready. No transaction was sent.',503)
                if '429' in stderr or 'rate limit' in stderr or 'too many requests' in stderr:
                    rpc_throttled_until[endpoint]=time.monotonic()+12
            if built is None:
                return fail('Solana RPC is busy. No claim transaction was prepared; retry shortly.',503)
            if (built.get('mint')!=row['mint'] or
                    built.get('quote_mint') != (USDC_MINT if row['quote_asset']=='USDC' else WSOL_MINT)
                    or not built.get('transaction_b64') or built.get('transaction_bytes',0)>1232):
                return fail('Reward builder returned inconsistent transaction',503)
            accrued=str(int(built.get('accrued_raw') or 0))
            if int(accrued)<=0:return fail('No creator fees have accrued yet',409)
            # Reserve the non-launch part of the 0.03 SOL test envelope for
            # ATA/rent + fee claims. Trades elsewhere need separate user
            # approval and are never charged through this launch endpoint.
            pilot_claim_cost=pilot_sol_preflight(row,built['transaction_b64'],
                                                 PILOT_MAX_FOLLOWUP_SOL_LAMPORTS,claim_read=(row['reward_mode']=='creator' and row['quote_asset']=='USDC'))
            claim_id=secrets.token_hex(16)
            with sqlite3.connect(d.DB_FILE) as conn:
                conn.execute('''INSERT INTO token_reward_claims
                  (id,launch_id,wallet,mint,quote_asset,reward_mode,accrued_raw,accrued_scope,
                   transaction_b64,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                  (claim_id,launch_id,wallet,row['mint'],row['quote_asset'],
                   row['reward_mode'],accrued,built.get('accrued_scope',''),
                   built['transaction_b64'],int(time.time())))
        except RuntimeError as exc:
            # A rejected simulation (including insufficient ATA rent) is a
            # controlled preflight refusal, not a production HTTP 500.
            return fail(exc,503)
        except (OSError,subprocess.TimeoutExpired,ValueError) as exc:
            return fail('Reward claim builder unavailable; nothing has been spent.',503)
        return jsonify(ok=True,claim_id=claim_id,transaction_b64=built['transaction_b64'],
              quote_asset=row['quote_asset'],accrued_raw=accrued,
              pilot_estimated_max_sol_lamports=pilot_claim_cost,
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
        if claim['status'] in ('confirmed','confirmed_no_payout'):
            if claim['signature']!=sig:return fail('Claim signature does not match',409)
            return jsonify(ok=True,confirmed=True,signature=sig,status=claim['status'],
                           received_raw=claim['received_raw'])
        if claim['status'] not in ('prepared','submitted'):
            return fail('Claim is not pending',409)
        try:
            exact={'prepare_tx_b64':claim['transaction_b64'],'wallet':wallet,'mint':row['mint']}
            confirmed=check_signature(sig,exact,'claim')
        except ValueError as exc:return fail(exc)
        except RuntimeError as exc:return fail(exc,503)
        received_raw=''
        if confirmed and row['reward_mode']=='creator' and row['quote_asset']=='USDC':
            try:received_raw=verified_creator_usdc_receipt(sig,wallet,allow_zero=True)
            except RuntimeError as exc:return fail(exc,503)
        status=('confirmed' if int(received_raw)>0 else 'confirmed_no_payout') if confirmed and row['reward_mode']=='creator' and row['quote_asset']=='USDC' else ('confirmed' if confirmed else 'submitted')
        with sqlite3.connect(d.DB_FILE) as conn:
            cur=conn.execute('''UPDATE token_reward_claims
                 SET signature=?,status=?,confirmed_at=?,received_raw=?
                 WHERE id=? AND wallet=? AND status IN ('prepared','submitted')
                 AND (signature='' OR signature=?)''',
                 (sig,status,int(time.time()) if confirmed else 0,received_raw,claim_id,wallet,sig))
            if cur.rowcount!=1:return fail('Claim changed during verification',409)
        return jsonify(ok=True,confirmed=confirmed,signature=sig,status=status,received_raw=received_raw), (200 if confirmed else 202)

    @app.get('/api/token-launch/<launch_id>/claims')
    @d.rate_limit(25,60)
    def reward_claim_history(launch_id):
        wallet=identity()
        if not wallet:return fail('Connect your wallet',401)
        row=lookup(launch_id,wallet)
        if not row:return fail('Launch not found',404)
        with closing(sqlite3.connect(d.DB_FILE)) as conn:
            claims=conn.execute('''SELECT id,quote_asset,accrued_raw,accrued_scope,
                             signature,status,created_at,confirmed_at,received_raw
                    FROM token_reward_claims WHERE launch_id=? AND wallet=?
                    ORDER BY created_at DESC LIMIT 30''',(launch_id,wallet)).fetchall()
        return jsonify(ok=True,claims=[dict(zip(('id','quote_asset','accrued_raw',
                     'accrued_scope','signature','status','created_at','confirmed_at','received_raw'),v)) for v in claims])

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

    # USDC funding is a separate, user-approved Jupiter gasless swap into
    # the creator's OWN Phantom wallet, never an OrcAgent-controlled debit.
    from token_launch_usdc_funding import install as install_usdc_launch_funding
    install_usdc_launch_funding(d)
    # Mobile links are separate from login: only the creator approves
    # the exact owner-bound Pump transaction, never an OrcAgent key.
    if os.getenv('ENCRYPTION_KEY'):
        from phantom_launch_mobile import install as install_phantom_launch_mobile
        install_phantom_launch_mobile(d,lookup,check_signature,mint_exists,sharing_check,blockhash_valid)
