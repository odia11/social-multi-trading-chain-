"""One-approval token launch: sign create + fee split together in Phantom.

No server key signs. The server accepts only the exact two prepared messages,
persists their signed bytes, then relays them in order. A retry can only relay
those same signatures; it can never create a second mint.
"""
import base64
import binascii
import sqlite3
import time

from solders.transaction import Transaction
from flask import jsonify, request


def install(d, *, lookup, shared, build_tx, pilot_sol_preflight, pilot_wallet,
            blockhash_valid, check_signature, mint_exists, row_sharing_ok,
            enabled, identity, csrf, fail, rpc, public_max, pilot_max,
            followup_max):
    app=d.app
    if getattr(app,'_orca_one_approval_installed',False):
        return app._orca_submit_one_approval
    app._orca_one_approval_installed=True

    def signed_exact(raw_b64,prepared_b64,row,*,create):
        try:
            if not isinstance(raw_b64,str) or len(raw_b64)>5000:raise ValueError
            raw=base64.b64decode(raw_b64,validate=True)
            if not 1<=len(raw)<=1232:raise ValueError
            signed=Transaction.from_bytes(raw)
            prepared=Transaction.from_bytes(base64.b64decode(prepared_b64,validate=True))
            if bytes(signed.message)!=bytes(prepared.message):raise ValueError
            if len(signed.signatures)!=len(prepared.signatures):raise ValueError
            if create and signed.signatures[1:]!=prepared.signatures[1:]:raise ValueError
            if not all(signed.verify_with_results()):raise ValueError
            if str(signed.message.account_keys[0])!=row['wallet']:raise ValueError
            signature=str(signed.signatures[0])
            if not 85<=len(signature)<=90:raise ValueError
            return raw,signature
        except (ValueError,TypeError,IndexError,binascii.Error) as exc:
            raise ValueError('Phantom signature did not match this exact saved launch') from exc

    def endpoints():
        return [__import__('os').environ.get('ORCA_LAUNCH_RPC',''),
                getattr(d,'SOLANA_RPC_URL','') or getattr(d,'SOLANA_RPC',''),
                'https://solana-rpc.publicnode.com',
                'https://api.mainnet-beta.solana.com']

    def advance(row,create_raw,finalize_raw,create_sig,finalize_sig):
        from launch_delivery import relay_identical_signed
        fresh=lookup(row['id'],row['wallet'])
        if fresh['status']=='live':
            return dict(ok=True,confirmed=True,live=True,mint=row['mint'],launch_id=row['id'],
                        create_signature=create_sig,finalize_signature=finalize_sig,
                        msg='Token launch confirmed. Your token is live on OrcAgent.')
        create_confirmed=fresh['status'] in ('pending_shares','finalize_submitted','live')
        if fresh['status']=='submitted':
            relay_identical_signed(create_raw,create_sig,endpoints(),reasons=[])
            try:
                create_confirmed=bool(check_signature(create_sig,fresh,'create')
                                      and mint_exists(fresh['mint']))
            except RuntimeError:
                create_confirmed=False
            if create_confirmed:
                with sqlite3.connect(d.DB_FILE,timeout=8) as db:
                    db.execute("""UPDATE token_launches SET status='pending_shares'
                        WHERE id=? AND wallet=? AND status='submitted'
                        AND launch_signature=?""",(row['id'],row['wallet'],create_sig))
        fresh=lookup(row['id'],row['wallet'])
        if not create_confirmed:
            return dict(ok=True,submitted=True,live=False,mint=row['mint'],launch_id=row['id'],
                        create_signature=create_sig,finalize_signature=finalize_sig,
                        msg='Launch approval saved. The token is confirming; the signed fee split is preserved and needs no second approval.')
        if fresh['status']=='pending_shares':
            with sqlite3.connect(d.DB_FILE,timeout=8) as db:
                db.execute("""UPDATE token_launches SET status='finalize_submitted'
                    WHERE id=? AND wallet=? AND status='pending_shares'
                    AND finalize_signature=?""",(row['id'],row['wallet'],finalize_sig))
            fresh=lookup(row['id'],row['wallet'])
        if fresh['status']=='finalize_submitted':
            relay_identical_signed(finalize_raw,finalize_sig,endpoints(),reasons=[])
            try:
                finalized=bool(check_signature(finalize_sig,fresh,'finalize')
                               and row_sharing_ok(fresh))
            except RuntimeError:
                finalized=False
            if finalized:
                with sqlite3.connect(d.DB_FILE,timeout=8) as db:
                    db.execute("""UPDATE token_launches SET status='live',finalized_at=?
                        WHERE id=? AND wallet=? AND status='finalize_submitted'
                        AND finalize_signature=?""",
                        (int(time.time()),row['id'],row['wallet'],finalize_sig))
                return dict(ok=True,confirmed=True,live=True,mint=row['mint'],launch_id=row['id'],
                            create_signature=create_sig,finalize_signature=finalize_sig,
                            msg='Token launch confirmed. Your token is live on OrcAgent.')
        return dict(ok=True,submitted=True,live=False,mint=row['mint'],launch_id=row['id'],
                    create_signature=create_sig,finalize_signature=finalize_sig,
                    msg='Token created. Your already-signed fee split is confirming; no second Phantom approval is needed.')

    def submit(row,signed_transactions):
        if not shared(row) or not row.get('prepare_tx_b64') or not row.get('finalize_tx_b64'):
            raise ValueError('This saved launch is not ready for one-approval signing')
        if not isinstance(signed_transactions,list) or len(signed_transactions)!=2:
            raise ValueError('Phantom must return both launch transactions')
        create_raw,create_sig=signed_exact(
            signed_transactions[0],row['prepare_tx_b64'],row,create=True)
        finalize_raw,finalize_sig=signed_exact(
            signed_transactions[1],row['finalize_tx_b64'],row,create=False)
        now=int(time.time())
        with sqlite3.connect(d.DB_FILE,timeout=8) as db:
            db.execute('BEGIN IMMEDIATE')
            db.row_factory=sqlite3.Row
            fresh=db.execute('SELECT * FROM token_launches WHERE id=? AND wallet=?',
                             (row['id'],row['wallet'])).fetchone()
            if not fresh:raise ValueError('Saved launch no longer exists')
            if fresh['launch_signature'] and fresh['launch_signature']!=create_sig:
                raise ValueError('A different launch transaction is already recorded')
            if fresh['finalize_signature'] and fresh['finalize_signature']!=finalize_sig:
                raise ValueError('A different fee-split transaction is already recorded')
            if fresh['status']=='prepared':
                cur=db.execute("""UPDATE token_launches
                    SET launch_signature=?,finalize_signature=?,status='submitted'
                    WHERE id=? AND wallet=? AND status='prepared'
                    AND (launch_signature='' OR launch_signature=?)
                    AND (finalize_signature='' OR finalize_signature=?)""",
                    (create_sig,finalize_sig,row['id'],row['wallet'],create_sig,finalize_sig))
                if cur.rowcount!=1:raise ValueError('Launch status changed before submission')
            elif fresh['status'] not in ('submitted','pending_shares','finalize_submitted','live'):
                raise ValueError('This launch cannot be submitted from its current state')
            db.execute("""INSERT INTO token_launch_one_approval
                (launch_id,wallet,create_signature,finalize_signature,
                 create_signed,finalize_signed,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(launch_id) DO UPDATE SET
                 create_signature=excluded.create_signature,
                 finalize_signature=excluded.finalize_signature,
                 create_signed=excluded.create_signed,
                 finalize_signed=excluded.finalize_signed,
                 updated_at=excluded.updated_at""",
                (row['id'],row['wallet'],create_sig,finalize_sig,
                 sqlite3.Binary(create_raw),sqlite3.Binary(finalize_raw),now,now))
        return advance(row,create_raw,finalize_raw,create_sig,finalize_sig)

    app._orca_submit_one_approval=submit

    @app.post('/api/token-launch/<launch_id>/prepare-one-approval')
    @d.rate_limit(4,60)
    def prepare_one_approval(launch_id):
        wallet=identity()
        if not wallet:return fail('Connect your wallet',401)
        if not csrf():return fail('CSRF validation failed',403)
        if not enabled():return fail('Token Launch is in preflight',503)
        row=lookup(launch_id,wallet)
        if not row:return fail('Launch not found',404)
        if row['status']!='prepared' or row['launch_signature']:
            return fail('Prepare the saved launch before requesting one approval',409)
        if not shared(row):
            return fail('This launch only needs one transaction; use normal approval',409)
        try:
            ceiling=pilot_max if pilot_wallet(wallet) else public_max
            if row.get('quote_asset')=='SOL':ceiling+=max(0,int(row.get('initial_buy_raw') or 0))
            create_cost=pilot_sol_preflight(row,row['prepare_tx_b64'],
                                            max_lamports=ceiling,enforce_public=True)
            balance=rpc('getBalance',[wallet,{'commitment':'confirmed'}],launch_read=True)
            available=(balance or {}).get('value')
            if type(available) is not int or available<create_cost+followup_max:
                raise RuntimeError('Insufficient SOL for the token launch plus its one-approval fee split. Add SOL or fund this saved draft with USDC first.')
            built=build_tx(row,'finalize')
            raw=base64.b64decode(built['transaction_b64'],validate=True)
            prepared=Transaction.from_bytes(raw)
            if (str(prepared.message.account_keys[0])!=wallet
                    or built.get('mint')!=row['mint'] or len(raw)>1232):
                raise RuntimeError('One-approval fee split could not be prepared safely')
            if not blockhash_valid(row['prepare_tx_b64']) or not blockhash_valid(built['transaction_b64']):
                raise RuntimeError('The signing window expired while preparing the launch. Retry this same saved draft.')
        except (RuntimeError,ValueError,TypeError,IndexError,binascii.Error) as exc:
            return fail(exc,503)
        with sqlite3.connect(d.DB_FILE,timeout=8) as db:
            cur=db.execute("""UPDATE token_launches SET finalize_tx_b64=?
                 WHERE id=? AND wallet=? AND status='prepared'
                 AND launch_signature='' """,
                 (built['transaction_b64'],launch_id,wallet))
            if cur.rowcount!=1:return fail('Launch changed while preparing one approval',409)
        return jsonify(ok=True,mint=row['mint'],
            transactions_b64=[row['prepare_tx_b64'],built['transaction_b64']],
            estimated_max_sol_lamports=create_cost+followup_max,
            one_approval=True,expires_in=45)

    @app.post('/api/token-launch/<launch_id>/one-approval/submit')
    @d.rate_limit(5,60)
    def submit_route(launch_id):
        wallet=identity()
        if not wallet:return fail('Connect your wallet',401)
        if not csrf():return fail('CSRF validation failed',403)
        row=lookup(launch_id,wallet)
        if not row:return fail('Launch not found',404)
        body=request.get_json(silent=True) or {}
        try:result=submit(row,body.get('transactions_b64'))
        except ValueError as exc:return fail(exc,409)
        except RuntimeError as exc:return fail(exc,503)
        return jsonify(**result),(200 if result.get('live') else 202)

    @app.post('/api/token-launch/<launch_id>/one-approval/retry')
    @d.rate_limit(8,60)
    def retry_route(launch_id):
        wallet=identity()
        if not wallet:return fail('Connect your wallet',401)
        if not csrf():return fail('CSRF validation failed',403)
        row=lookup(launch_id,wallet)
        if not row:return fail('Launch not found',404)
        with sqlite3.connect(d.DB_FILE) as db:
            saved=db.execute("""SELECT create_signed,finalize_signed
                FROM token_launch_one_approval WHERE launch_id=? AND wallet=?""",
                (launch_id,wallet)).fetchone()
        if not saved:return fail('No one-approval launch is saved for this token',404)
        signed=[base64.b64encode(bytes(saved[0])).decode(),
                base64.b64encode(bytes(saved[1])).decode()]
        try:result=submit(row,signed)
        except ValueError as exc:return fail(exc,409)
        except RuntimeError as exc:return fail(exc,503)
        return jsonify(**result),(200 if result.get('live') else 202)

    return submit
