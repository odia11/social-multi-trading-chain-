"""Equal SOL group tips, reviewed in USDC value, with durable signed batches.

Recipients and amounts are server-owned. Retrying a submitted quote only ever
rebroadcasts the same signed bytes, including after a restart.
"""
import base64
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from flask import jsonify, request

BATCH_SIZE = 16


def initialize(path):
    with sqlite3.connect(path) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS group_tips (
            id TEXT PRIMARY KEY, chat_id INTEGER NOT NULL, sender_id INTEGER NOT NULL,
            wallet TEXT NOT NULL, quote TEXT NOT NULL, created REAL NOT NULL,
            state TEXT NOT NULL DEFAULT 'quoted', plan TEXT, message_id INTEGER,
            attempt REAL NOT NULL DEFAULT 0)''')
        columns = {r[1] for r in c.execute('PRAGMA table_info(group_tips)')}
        if 'lease_until' not in columns:
            try:
                c.execute('ALTER TABLE group_tips ADD COLUMN lease_until REAL NOT NULL DEFAULT 0')
            except sqlite3.OperationalError as exc:
                if 'duplicate column' not in str(exc).lower():
                    raise
        c.execute('CREATE INDEX IF NOT EXISTS idx_group_tip_pending ON group_tips(state,created)')


@contextmanager
def _db(d):
    c = sqlite3.connect(d.DB_FILE, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def _recipients(d, c, chat_id, uid):
    import portfolio_token_withdraw as provider
    if chat_id > 0 and not c.execute('SELECT 1 FROM group_chat_members WHERE chat_id=? AND user_id=?', (chat_id, uid)).fetchone():
        raise ValueError('Group not found')
    rows = (c.execute('SELECT id,username,avatar_url FROM users WHERE id=? AND id!=?', (-chat_id, uid)).fetchall() if chat_id < 0 else c.execute('SELECT u.id,u.username,u.avatar_url FROM group_chat_members m JOIN users u ON u.id=m.user_id WHERE m.chat_id=? AND u.id!=? ORDER BY u.id', (chat_id, uid)).fetchall())
    if not rows or len(rows) > 49:
        raise ValueError('A group tip needs 1 to 49 other members')
    result = []
    for row in rows:
        target = provider._user_tip_wallets(d, row[0])
        address = target['solana'] if target else ''
        if not d.is_valid_solana_address(address):
            raise ValueError('A member needs to set up a Solana wallet before the group can receive a tip')
        result.append({'user_id': row[0], 'username': row[1] or 'OrcAgent member', 'avatar': row[2] or '', 'address': address})
    if len({r['address'] for r in result}) != len(result):
        raise ValueError('Group members must have distinct receiving wallets')
    return result


def _snapshot(rows):
    return [(r['user_id'], r['address']) for r in rows]


def _messages(owner, recipients, amount, blockhash, memo):
    from solders.pubkey import Pubkey
    from solders.hash import Hash
    from solders.message import Message
    from solders.system_program import transfer, TransferParams
    from solders.instruction import Instruction
    source = Pubkey.from_string(owner)
    marker = Instruction(Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"), memo.encode(), [])
    return [Message.new_with_blockhash([
        transfer(TransferParams(from_pubkey=source, to_pubkey=Pubkey.from_string(r['address']), lamports=amount))
        for r in recipients[i:i+BATCH_SIZE]] + [marker], source, Hash.from_string(blockhash))
        for i in range(0, len(recipients), BATCH_SIZE)]


def _public_quote(row, uid):
    q = json.loads(row['quote'])
    own = uid == row['sender_id']
    recipient = next((r for r in q['recipients'] if r['user_id'] == uid), None)
    result = {'id': row['id'], 'status': row['state'], 'recipient_count': len(q['recipients']),
              'note': q['note'], 'sender': own, 'recipient': bool(recipient), 'expires_at': q['expires'],
              'message_id': row['message_id']}
    if own or recipient:
        result.update(per_person_sol=q['per'] / 1e9, per_person_usdc=float(Decimal(q['price']) * q['per'] / Decimal(1e9)))
    if own:
        result.update(amount_usdc=q['usd'], total_sol=q['total'] / 1e9, fee_sol=q['fee'] / 1e9,
                      total_debit_sol=(q['total'] + q['fee']) / 1e9, price_usdc=float(q['price']),
                      recipients=[{k: r[k] for k in ('user_id', 'username', 'avatar')} for r in q['recipients']])
    if row['plan']:
        p = json.loads(row['plan'])
        result['confirmed_recipients'] = sum(len(b['users']) for b in p if b['state'] == 'confirmed')
        if own or recipient:
            result['transactions'] = [{'status': b['state'], 'explorer': 'https://solscan.io/tx/' + b['signature']}
                                      for b in p if own or uid in b['users']]
    return result


def reconcile(d, tip_id):
    # Cross-worker claim; a crashed worker can resume the exact signed bytes.
    with _db(d) as c:
        claimed = c.execute("UPDATE group_tips SET lease_until=? WHERE id=? AND state='submitted' AND lease_until<?", (time.time()+300, tip_id, time.time())).rowcount
    if not claimed:
        return
    try:
        _reconcile_locked(d, tip_id)
    finally:
        with _db(d) as c:
            c.execute("UPDATE group_tips SET lease_until=0 WHERE id=?", (tip_id,))


def _reconcile_locked(d, tip_id):
    import portfolio_token_withdraw as provider
    import tip_experience as ledger
    with _db(d) as c:
        row = c.execute('SELECT * FROM group_tips WHERE id=?', (tip_id,)).fetchone()
    if not row or row['state'] not in ('submitted',):
        return
    with provider._lock_for(row['wallet'], 'solana'):
        with _db(d) as c:
            row = c.execute('SELECT * FROM group_tips WHERE id=?', (tip_id,)).fetchone()
        if row['state'] != 'submitted':
            return
        q, plan = json.loads(row['quote']), json.loads(row['plan'])
        # Backfill the normal, private Portfolio ledger before broadcasting.
        # An interrupted write can be resumed without duplicate recipient rows.
        for batch in plan:
            for r in q['recipients']:
                if r['user_id'] in batch['users']:
                    ledger.record_submitted(d, row['wallet'], row['sender_id'], r['user_id'], r['address'],
                                            q['per'] / 1e9, 'solana', batch['signature'], q['note'], 'SOL')
        statuses, _ = provider._rpc_call_any(d, 'getSignatureStatuses',
            [[b['signature'] for b in plan], {'searchTransactionHistory': True}])
        values = statuses.get('value') if isinstance(statuses, dict) else None
        if not isinstance(values, list) or len(values) != len(plan):
            return
        height = None
        if any(v is None for v in values):
            height, _ = provider._rpc_call_any(d, 'getBlockHeight', [{'commitment': 'finalized'}])
            if not isinstance(height, int):
                return
        for batch, status in zip(plan, values):
            if batch['state'] in ('confirmed', 'failed'):
                continue
            if status and status.get('err') is not None:
                batch['state'] = 'failed'
            elif status and status.get('confirmationStatus') in ('confirmed', 'finalized'):
                batch['state'] = 'confirmed'
            elif status is None and height > q['last_height']:
                batch['state'] = 'failed'
            if batch['state'] in ('confirmed', 'failed'):
                with _db(d) as c:
                    tips = c.execute('SELECT id FROM tip_transactions WHERE tx_hash=? AND sender_user_id=?',
                                     (batch['signature'], row['sender_id'])).fetchall()
                for tip in tips:
                    ledger._transition(d, tip['id'], batch['state'], 'Group tip transaction failed or expired' if batch['state'] == 'failed' else None)
        pending = any(b['state'] == 'submitted' for b in plan)
        state = 'submitted' if pending else ('confirmed' if all(b['state'] == 'confirmed' for b in plan)
                                             else 'partial' if any(b['state'] == 'confirmed' for b in plan) else 'failed')
        body = json.dumps({'tip_id': tip_id, 'count': len(q['recipients']), 'note': q['note'], 'status': state,
                           'confirmed': sum(len(b['users']) for b in plan if b['state'] == 'confirmed')})
        with _db(d) as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('UPDATE group_tips SET plan=?,state=? WHERE id=?', (json.dumps(plan), state, tip_id))
            old = c.execute('SELECT body FROM group_chat_messages WHERE id=?', (row['message_id'],)).fetchone() if row['chat_id'] > 0 else None
            if row['chat_id'] < 0:
                c.execute('UPDATE direct_messages SET message=? WHERE id=?', (body, row['message_id']))
            if old and old['body'] != body:
                c.execute('UPDATE group_chats SET change_version=change_version+1 WHERE id=?', (row['chat_id'],))
                version = c.execute('SELECT change_version FROM group_chats WHERE id=?', (row['chat_id'],)).fetchone()[0]
                c.execute('UPDATE group_chat_messages SET body=?,version=? WHERE id=?', (body, version, row['message_id']))
        if not pending or time.time() - row['attempt'] < 20:
            return
        with _db(d) as c:
            c.execute('UPDATE group_tips SET attempt=? WHERE id=?', (time.time(), tip_id))
        for batch in plan:
            if batch['state'] != 'submitted':
                continue
            try:
                # Never re-sign on timeouts or after expiry. Same bytes, same ID.
                provider._rpc_call_any(d, 'sendTransaction', [batch['encoded'],
                    {'encoding': 'base64', 'skipPreflight': False, 'preflightCommitment': 'confirmed', 'maxRetries': 3}])
            except Exception:
                # A transport failure is not proof that no payment happened.
                continue


def install(d):
    import portfolio_token_withdraw as provider
    app = d.app
    if app.config.get('GROUP_TIPS_INSTALLED'):
        return
    app.config['GROUP_TIPS_INSTALLED'] = True
    initialize(d.DB_FILE)

    @app.after_request
    def tip_cache_control(response):
        if request.path.startswith(('/api/group-chats/', '/api/messages/')) and '/tips' in request.path:
            response.headers['Cache-Control'] = 'private, no-store'
        return response

    def identity(chat_id):
        wallet = d._authenticated_wallet()
        if not wallet:
            raise PermissionError('Authentication required')
        with _db(d) as c:
            uid = d._get_uid(c, wallet)
            if not uid or (chat_id > 0 and not c.execute('SELECT 1 FROM group_chat_members WHERE chat_id=? AND user_id=?', (chat_id, uid)).fetchone()) or (chat_id < 0 and (-chat_id == uid or not c.execute('SELECT 1 FROM users WHERE id=?', (-chat_id,)).fetchone())):
                raise PermissionError('Group not found')
        return wallet, uid

    def error(exc):
        if isinstance(exc, PermissionError):
            return jsonify(ok=False, msg=str(exc)), 403
        if isinstance(exc, ValueError):
            return jsonify(ok=False, msg=str(exc)), 400
        app.logger.warning('group tip unavailable: %s', type(exc).__name__)
        return jsonify(ok=False, msg='Group tip unavailable. Check your tip details before trying again.'), 503

    @app.post('/api/group-chats/<int:chat_id>/tips/quote')
    @d.rate_limit(12, 60)
    def quote(chat_id):
        try:
            wallet, uid = identity(chat_id)
            if not provider._csrf_ok(d):
                raise PermissionError('CSRF validation failed')
            body = request.get_json(silent=True) or {}
            if not isinstance(body, dict):
                raise ValueError('Invalid tip request')
            try:
                usd = Decimal(str(body.get('amount_usdc')))
            except InvalidOperation:
                raise ValueError('Enter a valid USDC value')
            if not usd.is_finite() or usd < Decimal('.01') or usd > 10000:
                raise ValueError('Enter a USDC value from 0.01 to 10,000')
            snapshot = d._major_quote_snapshot()
            sol = snapshot.get('prices', {}).get('SOL', {})
            price = Decimal(str(sol.get('price') or 0))
            if not price.is_finite() or price <= 0 or time.time() - float(sol.get('observed_at') or 0) > 15:
                raise ValueError('A fresh SOL price is unavailable. Try again shortly.')
            with _db(d) as c:
                recipients = _recipients(d, c, chat_id, uid)
            owner = d._get_trading_wallet_address(wallet)
            if not owner or not provider._wallet_keys(d, wallet):
                raise ValueError('Create or connect your Solana trading wallet first')
            if owner in {r['address'] for r in recipients}:
                raise ValueError('You cannot tip your own wallet through another member')
            count = len(recipients)
            per = int((usd / price * Decimal(1e9) / count).to_integral_value(rounding=ROUND_DOWN))
            if per < 1 or usd / count < Decimal('.01'):
                raise ValueError('The minimum tip value is 0.01 USDC per member')
            total = per * count
            if total > 100 * 10**9:
                raise ValueError('The group tip exceeds the 100 SOL limit')
            block, _ = provider._rpc_call_any(d, 'getLatestBlockhash', [{'commitment': 'confirmed'}])
            from solders.message import to_bytes_versioned
            block = block['value']
            tid = uuid.uuid4().hex
            messages = _messages(owner, recipients, per, block['blockhash'], tid)
            fees = []
            for msg in messages:
                fee, _ = provider._rpc_call_any(d, 'getFeeForMessage', [base64.b64encode(to_bytes_versioned(msg)).decode(), {'commitment': 'confirmed'}])
                value = fee.get('value') if isinstance(fee, dict) else None
                if type(value) is not int or value <= 0:
                    raise ValueError('Cannot verify the network fee. No tip was sent.')
                fees.append(value)
            balance, _ = provider._rpc_call_any(d, 'getBalance', [owner, {'commitment': 'confirmed'}])
            floor = max(provider._fee_payer_rent_lamports(d), int(d.SOL_NETWORK_RESERVE * 1e9))
            if int(balance['value']) < total + sum(fees) + floor:
                raise ValueError('Not enough SOL for this tip, network fees and the wallet reserve')
            q = {'recipients': recipients, 'owner': owner, 'price': str(price), 'usd': float(usd), 'per': per,
                 'total': total, 'fee': sum(fees), 'fees': fees, 'blockhash': block['blockhash'],
                 'last_height': block['lastValidBlockHeight'], 'expires': time.time() + 45,
                 'note': d._sanitize(str(body.get('message') or '')).strip()[:100]}
            with _db(d) as c:
                c.execute("DELETE FROM group_tips WHERE state='quoted' AND created<?", (time.time()-86400,))
                c.execute('INSERT INTO group_tips(id,chat_id,sender_id,wallet,quote,created) VALUES(?,?,?,?,?,?)',
                          (tid, chat_id, uid, wallet, json.dumps(q), time.time()))
                row = c.execute('SELECT * FROM group_tips WHERE id=?', (tid,)).fetchone()
            return jsonify(ok=True, tip=_public_quote(row, uid))
        except Exception as exc:
            return error(exc)

    @app.post('/api/group-chats/<int:chat_id>/tips/<tip_id>/confirm')
    @d.rate_limit(12, 60)
    def confirm(chat_id, tip_id):
        try:
            wallet, uid = identity(chat_id)
            if not provider._csrf_ok(d):
                raise PermissionError('CSRF validation failed')
            lock = provider._lock_for(wallet, 'solana')
            with lock:
                with _db(d) as c:
                    row = c.execute('SELECT * FROM group_tips WHERE id=? AND chat_id=? AND sender_id=?', (tip_id, chat_id, uid)).fetchone()
                if not row:
                    raise PermissionError('Tip not found')
                if row['state'] != 'quoted':
                    return jsonify(ok=True, tip=_public_quote(row, uid))
                q = json.loads(row['quote'])
                if callable(getattr(d, '_rate_ok', None)) and not d._rate_ok('tip_wallet:' + wallet, 12, 3600):
                    raise ValueError('Tip limit reached. Try again later.')
                if time.time() > q['expires']:
                    raise ValueError('This quote expired. Review a fresh quote before sending.')
                with _db(d) as c:
                    if _snapshot(_recipients(d, c, chat_id, uid)) != _snapshot(q['recipients']):
                        raise ValueError('Group members or receiving wallets changed. Review a fresh quote.')
                keyrow = provider._wallet_keys(d, wallet)
                from solders.keypair import Keypair
                from solders.transaction import Transaction
                from solders.hash import Hash
                from solders.message import to_bytes_versioned
                plan = []
                with d._use_key(keyrow[0], wallet) as secret:
                    key = Keypair.from_base58_string(secret)
                    if str(key.pubkey()) != q['owner']:
                        raise ValueError('Your trading wallet changed. Review a fresh quote.')
                    balance, _ = provider._rpc_call_any(d, 'getBalance', [q['owner'], {'commitment': 'confirmed'}])
                    floor = max(provider._fee_payer_rent_lamports(d), int(d.SOL_NETWORK_RESERVE * 1e9))
                    if int(balance['value']) < q['total'] + q['fee'] + floor:
                        raise ValueError('Not enough SOL for the reviewed total and wallet reserve')
                    for i, msg in enumerate(_messages(q['owner'], q['recipients'], q['per'], q['blockhash'], tip_id)):
                        fee, _ = provider._rpc_call_any(d, 'getFeeForMessage', [base64.b64encode(to_bytes_versioned(msg)).decode(), {'commitment': 'confirmed'}])
                        if not isinstance(fee, dict) or fee.get('value') != q['fees'][i]:
                            raise ValueError('Network fee changed. Review a fresh quote.')
                        tx = Transaction([key], msg, Hash.from_string(q['blockhash']))
                        if len(bytes(tx)) > 1232:
                            raise ValueError('Group tip transaction is too large')
                        encoded = base64.b64encode(bytes(tx)).decode()
                        result, _ = provider._rpc_call_any(d, 'simulateTransaction', [encoded, {'encoding': 'base64', 'sigVerify': True, 'commitment': 'confirmed'}])
                        if not isinstance(result, dict) or not isinstance(result.get('value'), dict) or result['value'].get('err') is not None:
                            raise ValueError('A receiving wallet or the network rejected this tip. Nothing was sent.')
                        plan.append({'users': [r['user_id'] for r in q['recipients'][i*BATCH_SIZE:(i+1)*BATCH_SIZE]],
                                     'signature': str(tx.signatures[0]), 'encoded': encoded, 'state': 'submitted'})
                with _db(d) as c:
                    c.execute('BEGIN IMMEDIATE')
                    current = c.execute('SELECT * FROM group_tips WHERE id=?', (tip_id,)).fetchone()
                    if current['state'] != 'quoted':
                        return jsonify(ok=True, tip=_public_quote(current, uid))
                    if time.time() > q['expires'] or _snapshot(_recipients(d, c, chat_id, uid)) != _snapshot(q['recipients']):
                        raise ValueError('The quote or group changed. Review again; nothing was sent.')
                    body = json.dumps({'tip_id': tip_id, 'count': len(q['recipients']), 'note': q['note'], 'status': 'submitted', 'confirmed': 0})
                    if chat_id > 0:
                        mid = c.execute("INSERT INTO group_chat_messages(chat_id,sender_id,kind,body,created_at) VALUES(?,?,'tip',?,datetime('now'))", (chat_id, uid, body)).lastrowid
                    else:
                        mid = c.execute("INSERT INTO direct_messages(sender_id,receiver_id,message,message_type) VALUES(?,?,?,'tip_receipt')", (uid, -chat_id, body)).lastrowid
                    c.execute("UPDATE group_tips SET state='submitted',plan=?,message_id=? WHERE id=?", (json.dumps(plan), mid, tip_id))
                    row = c.execute('SELECT * FROM group_tips WHERE id=?', (tip_id,)).fetchone()
            try:
                reconcile(d, tip_id)
            except Exception:
                pass
            with _db(d) as c:
                row = c.execute('SELECT * FROM group_tips WHERE id=?', (tip_id,)).fetchone()
            return jsonify(ok=True, tip=_public_quote(row, uid))
        except Exception as exc:
            return error(exc)

    @app.get('/api/group-chats/<int:chat_id>/tips/<tip_id>')
    @d.rate_limit(30, 60)
    def detail(chat_id, tip_id):
        try:
            wallet, uid = identity(chat_id)
            with _db(d) as c:
                row = c.execute('SELECT * FROM group_tips WHERE id=? AND chat_id=?', (tip_id, chat_id)).fetchone()
                floor = (c.execute('SELECT history_from_id FROM group_chat_members WHERE chat_id=? AND user_id=?', (chat_id, uid)).fetchone()[0] or 0) if chat_id > 0 else 0
            if not row or (chat_id < 0 and uid not in (row['sender_id'], -chat_id)) or (row['state'] == 'quoted' and row['sender_id'] != uid) or (row['message_id'] and row['message_id'] <= floor):
                raise PermissionError('Tip not found')
            return jsonify(ok=True, tip=_public_quote(row, uid))
        except Exception as exc:
            return error(exc)

    # Direct messages use the same reviewed payment engine, with one recipient.
    @app.post('/api/messages/<int:peer_id>/tips/quote')
    @d.rate_limit(12, 60)
    def dm_quote(peer_id):
        return quote(-peer_id)

    @app.post('/api/messages/<int:peer_id>/tips/<tip_id>/confirm')
    @d.rate_limit(12, 60)
    def dm_confirm(peer_id, tip_id):
        return confirm(-peer_id, tip_id)

    @app.get('/api/messages/<int:peer_id>/tips/<tip_id>')
    @d.rate_limit(30, 60)
    def dm_detail(peer_id, tip_id):
        # A received receipt is stored against its recipient, not its sender.
        wallet = d._authenticated_wallet()
        if not wallet:
            return error(PermissionError('Authentication required'))
        with _db(d) as c:
            uid = d._get_uid(c, wallet)
            row = c.execute('SELECT * FROM group_tips WHERE id=? AND chat_id<0', (tip_id,)).fetchone()
        if not row or not uid or {uid, peer_id} != {row['sender_id'], -row['chat_id']} or (row['state'] == 'quoted' and uid != row['sender_id']):
            return error(PermissionError('Tip not found'))
        return jsonify(ok=True, tip=_public_quote(row, uid))

    def reconcile_pending():
        with _db(d) as c:
            rows = c.execute("SELECT id FROM group_tips WHERE state='submitted' ORDER BY attempt LIMIT 3").fetchall()
        for row in rows:
            try:
                reconcile(d, row['id'])
            except Exception:
                pass

    d._group_tip_reconcile = reconcile_pending
