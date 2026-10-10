"""Equal SOL group tips, reviewed in USDC value, with durable signed batches.

Recipients and amounts are server-owned. Retrying a submitted quote only ever
rebroadcasts the same signed bytes, including after a restart.
"""
import base64
import json
import sqlite3
import time
import threading
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


def _recipients(d, c, chat_id, uid, own_addresses=()):
    import portfolio_token_withdraw as provider
    # A sender is never a recipient, even when a second member account points
    # at the sender's login wallet or custodial trading wallet.
    own_addresses = {str(address) for address in own_addresses if address}
    if chat_id > 0 and not c.execute('SELECT 1 FROM group_chat_members WHERE chat_id=? AND user_id=?', (chat_id, uid)).fetchone():
        raise ValueError('Group not found')
    rows = (c.execute('SELECT id,username,avatar_url FROM users WHERE id=? AND id!=?', (-chat_id, uid)).fetchall() if chat_id < 0 else c.execute('SELECT u.id,u.username,u.avatar_url FROM group_chat_members m JOIN users u ON u.id=m.user_id WHERE m.chat_id=? AND u.id!=? ORDER BY u.id', (chat_id, uid)).fetchall())
    if not rows or len(rows) > 49:
        raise ValueError('A group tip needs 1 to 49 other members')
    result = []
    for row in rows:
        if row[0] == uid:
            continue
        target = provider._user_tip_wallets(d, row[0])
        address = target['solana'] if target else ''
        if target and (address in own_addresses or target['session'] in own_addresses):
            continue
        if not d.is_valid_solana_address(address):
            raise ValueError('A member needs to set up a Solana wallet before the group can receive a tip')
        result.append({'user_id': row[0], 'username': row[1] or 'OrcAgent member', 'avatar': row[2] or '', 'address': address})
    if not result:
        raise ValueError('There are no other eligible members to tip')
    if len({r['address'] for r in result}) != len(result):
        raise ValueError('Group members must have distinct receiving wallets')
    return result


def _recipient_version(c, chat_id, uid):
    """Opaque DB state only: never derive wallets or audit keys under a write lock."""
    sql = ('SELECT id,wallet_address,encrypted_private_key FROM users WHERE id IN (?,?) ORDER BY id'
           if chat_id < 0 else
           'SELECT u.id,u.wallet_address,u.encrypted_private_key FROM group_chat_members m JOIN users u ON u.id=m.user_id WHERE m.chat_id=? ORDER BY u.id')
    args = (uid, -chat_id) if chat_id < 0 else (chat_id,)
    return tuple(tuple(row) for row in c.execute(sql, args))


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
        errors = [b.get('error') for b in p if b['state'] != 'confirmed' and b.get('error') in _ERROR_TEXT]
        if errors:
            result['status_detail'] = _ERROR_TEXT[errors[0]]
        result['confirmed_recipients'] = sum(len(b['users']) for b in p if b['state'] == 'confirmed')
        if own or recipient:
            result['transactions'] = [{'status': b['state'], 'explorer': 'https://solscan.io/tx/' + b['signature']}
                                      for b in p if own or uid in b['users']]
    return result


def _quote_read(d, method, params, preferred_url=None):
    """Bounded read-only Solana RPC for the pre-payment quote screen.

    Trading and tip submission deliberately retain their normal RPC retries;
    only these pre-authorization checks need a short, user-visible deadline.
    """
    import portfolio_token_withdraw as provider
    try:
        return provider._rpc_call_any(
            d, method, params, preferred_url=preferred_url,
            timeout=2.5, max_providers=3)
    except Exception as exc:
        d.app.logger.warning('group tip quote RPC %s failed: %s',
                             method, type(exc).__name__)
        raise ValueError('Solana did not respond in time. No tip was sent. Try again.') from exc


def _preferred_rpc(d, q):
    import portfolio_token_withdraw as provider
    urls = provider._rpc_urls(d)
    index = q.get('rpc_index')
    return urls[index] if isinstance(index, int) and 0 <= index < len(urls) else None


_ERROR_TEXT = {
    'expired_blockhash': 'A transfer expired before confirmation.',
    'insufficient_sol': 'The network rejected the available SOL balance or account reserve.',
    'program_rejected': 'The network rejected this transaction.',
    'network_retry': 'Network response delayed. Checking the same payment; do not send another tip.',
    'chain_failed': 'The transaction failed on-chain. No funds were delivered by this transaction.',
}


def _broadcast(d, row, q, plan):
    import portfolio_token_withdraw as provider
    # Persist the attempt before contacting the network. A lost response is
    # always reconciled/rebroadcast with the SAME signature, never re-signed.
    with _db(d) as c:
        c.execute('UPDATE group_tips SET attempt=? WHERE id=?', (time.time(), row['id']))
    for batch in plan:
        if batch['state'] != 'submitted':
            continue
        try:
            provider._rpc_call_any(d, 'sendTransaction', [batch['encoded'],
                {'encoding': 'base64', 'skipPreflight': False,
                 'preflightCommitment': 'confirmed', 'maxRetries': 3}],
                preferred_url=_preferred_rpc(d, q))
            batch.pop('error', None)
        except Exception as exc:
            code = getattr(exc, 'reason_code', 'network_retry')
            batch['error'] = code if code in _ERROR_TEXT else 'network_retry'
            d.app.logger.warning('chat tip %s broadcast deferred: %s', row['id'][:8], batch['error'])
    with _db(d) as c:
        c.execute('UPDATE group_tips SET plan=? WHERE id=?', (json.dumps(plan), row['id']))


def _archived_status(d, signature, q):
    """A missing status alone is not evidence of failure: read the transaction."""
    import portfolio_token_withdraw as provider
    tx, _ = provider._rpc_call_any(d, 'getTransaction',
        [signature, {'commitment': 'confirmed', 'maxSupportedTransactionVersion': 0}],
        preferred_url=_preferred_rpc(d, q))
    if tx is None:
        return 'expired'
    if isinstance(tx, dict) and isinstance(tx.get('meta'), dict):
        return 'failed' if tx['meta'].get('err') is not None else 'confirmed'
    return 'unknown'


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
        if not row['attempt']:
            # Send first. An unavailable status RPC must not hold an already
            # authorised payment until its blockhash expires.
            _broadcast(d, row, q, plan)
            return
        statuses, _ = provider._rpc_call_any(d, 'getSignatureStatuses',
            [[b['signature'] for b in plan], {'searchTransactionHistory': True}], preferred_url=_preferred_rpc(d, q))
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
                batch['error'] = 'chain_failed'
            elif status and status.get('confirmationStatus') in ('confirmed', 'finalized'):
                batch['state'] = 'confirmed'
            elif status is None and height > q['last_height']:
                archived = _archived_status(d, batch['signature'], q)
                if archived == 'confirmed':
                    batch['state'] = 'confirmed'
                elif archived in ('expired', 'failed'):
                    batch['state'] = 'failed'
                    batch['error'] = 'expired_blockhash' if archived == 'expired' else 'chain_failed'
            if batch['state'] == 'confirmed':
                batch.pop('error', None)
            if batch['state'] in ('confirmed', 'failed'):
                with _db(d) as c:
                    tips = c.execute('SELECT id FROM tip_transactions WHERE tx_hash=? AND sender_user_id=?',
                                     (batch['signature'], row['sender_id'])).fetchall()
                for tip in tips:
                    ledger._transition(d, tip['id'], batch['state'], _ERROR_TEXT.get(batch.get('error'), 'Transaction failed') if batch['state'] == 'failed' else None)
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
        if pending and time.time() - row['attempt'] >= 3:
            _broadcast(d, row, q, plan)


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
            owner = d._get_trading_wallet_address(wallet)
            if not owner or not provider._wallet_keys(d, wallet):
                raise ValueError('Create or connect your Solana trading wallet first')
            with _db(d) as c:
                recipients = _recipients(d, c, chat_id, uid, (wallet, owner))
            if any(r['user_id'] == uid or r['address'] in (wallet, owner) for r in recipients):
                raise ValueError('You cannot tip yourself')
            count = len(recipients)
            per = int((usd / price * Decimal(1e9) / count).to_integral_value(rounding=ROUND_DOWN))
            if per < 1 or usd / count < Decimal('.01'):
                raise ValueError('The minimum tip value is 0.01 USDC per member')
            total = per * count
            if total > 100 * 10**9:
                raise ValueError('The group tip exceeds the 100 SOL limit')
            block, quote_rpc_url = _quote_read(d, 'getLatestBlockhash', [{'commitment': 'confirmed'}])
            from solders.message import to_bytes_versioned
            block = block['value']
            tid = uuid.uuid4().hex
            messages = _messages(owner, recipients, per, block['blockhash'], tid)
            fees = []
            for msg in messages:
                fee, _ = _quote_read(d, 'getFeeForMessage', [base64.b64encode(to_bytes_versioned(msg)).decode(), {'commitment': 'confirmed'}], preferred_url=quote_rpc_url)
                value = fee.get('value') if isinstance(fee, dict) else None
                if type(value) is not int or value <= 0:
                    raise ValueError('Cannot verify the network fee. No tip was sent.')
                fees.append(value)
            balance, _ = _quote_read(d, 'getBalance', [owner, {'commitment': 'confirmed'}], preferred_url=quote_rpc_url)
            # A plain Solana wallet needs at least this rent floor. The
            # confirmation stage separately rechecks the live network floor.
            # Avoid another potentially slow RPC on the review screen.
            floor = max(provider._FEE_PAYER_RENT_FALLBACK, int(d.SOL_NETWORK_RESERVE * 1e9))
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
                owner = d._get_trading_wallet_address(wallet)
                if not owner or any(r['user_id'] == uid or r['address'] in (wallet, owner)
                                    for r in q['recipients']):
                    raise ValueError('A tip cannot include your own account. Review a new tip.')
                if callable(getattr(d, '_rate_ok', None)) and not d._rate_ok('tip_wallet:' + wallet, 12, 3600):
                    raise ValueError('Tip limit reached. Try again later.')
                if time.time() > q['expires']:
                    raise ValueError('This quote expired. Review a fresh quote before sending.')
                with _db(d) as c:
                    recipient_version = _recipient_version(c, chat_id, uid)
                    if _snapshot(_recipients(d, c, chat_id, uid, (wallet, owner))) != _snapshot(q['recipients']):
                        raise ValueError('Group members or receiving wallets changed. Review a fresh quote.')
                keyrow = provider._wallet_keys(d, wallet)
                from solders.keypair import Keypair
                from solders.transaction import Transaction
                from solders.hash import Hash
                from solders.message import to_bytes_versioned
                # The review's blockhash may already be old. Refresh it BEFORE
                # signing; amounts, recipients and reviewed fees remain fixed.
                fresh, rpc_url = provider._rpc_call_any(d, 'getLatestBlockhash', [{'commitment': 'confirmed'}])
                q['blockhash'] = fresh['value']['blockhash']
                q['last_height'] = fresh['value']['lastValidBlockHeight']
                urls = provider._rpc_urls(d)
                q['rpc_index'] = urls.index(rpc_url) if rpc_url in urls else None
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
                        result, _ = provider._rpc_call_any(d, 'simulateTransaction', [encoded, {'encoding': 'base64', 'sigVerify': True, 'commitment': 'confirmed'}], preferred_url=rpc_url)
                        if not isinstance(result, dict) or not isinstance(result.get('value'), dict) or result['value'].get('err') is not None:
                            raise ValueError('A receiving wallet or the network rejected this tip. Nothing was sent.')
                        plan.append({'users': [r['user_id'] for r in q['recipients'][i*BATCH_SIZE:(i+1)*BATCH_SIZE]],
                                     'signature': str(tx.signatures[0]), 'encoded': encoded, 'state': 'submitted'})
                with _db(d) as c:
                    c.execute('BEGIN IMMEDIATE')
                    current = c.execute('SELECT * FROM group_tips WHERE id=?', (tip_id,)).fetchone()
                    if current['state'] != 'quoted':
                        return jsonify(ok=True, tip=_public_quote(current, uid))
                    if time.time() > q['expires'] or _recipient_version(c, chat_id, uid) != recipient_version:
                        raise ValueError('The quote or group changed. Review again; nothing was sent.')
                    body = json.dumps({'tip_id': tip_id, 'count': len(q['recipients']), 'note': q['note'], 'status': 'submitted', 'confirmed': 0})
                    if chat_id > 0:
                        mid = c.execute("INSERT INTO group_chat_messages(chat_id,sender_id,kind,body,created_at) VALUES(?,?,'tip',?,datetime('now'))", (chat_id, uid, body)).lastrowid
                    else:
                        mid = c.execute("INSERT INTO direct_messages(sender_id,receiver_id,message,message_type) VALUES(?,?,?,'tip_receipt')", (uid, -chat_id, body)).lastrowid
                    c.execute("UPDATE group_tips SET state='submitted',plan=?,message_id=?,quote=? WHERE id=?", (json.dumps(plan), mid, json.dumps(q), tip_id))
                    row = c.execute('SELECT * FROM group_tips WHERE id=?', (tip_id,)).fetchone()
            try:
                reconcile(d, tip_id)
            except Exception as exc:
                app.logger.warning('chat tip %s submission deferred: %s', tip_id[:8], type(exc).__name__)
            wake.set()
            with _db(d) as c:
                row = c.execute('SELECT * FROM group_tips WHERE id=?', (tip_id,)).fetchone()
            return jsonify(ok=True, tip=_public_quote(row, uid))
        except Exception as exc:
            return error(exc)

    @app.get('/api/group-chats/<int:chat_id>/tips/<tip_id>')
    @d.rate_limit(60, 60)
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
    @d.rate_limit(60, 60)
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
            rows = c.execute("SELECT id FROM group_tips WHERE state='submitted' ORDER BY attempt LIMIT 6").fetchall()
        for row in rows:
            try:
                reconcile(d, row['id'])
            except Exception as exc:
                app.logger.warning('chat tip confirmation deferred: %s', type(exc).__name__)
        return bool(rows)

    wake = threading.Event()

    def watch():
        while True:
            try:
                pending = reconcile_pending()
            except Exception as exc:
                app.logger.warning('chat tip watcher unavailable: %s', type(exc).__name__)
                pending = False
            wake.wait(2 if pending else 15)
            wake.clear()

    d._group_tip_reconcile = reconcile_pending
    threading.Thread(target=watch, name='orca-chat-tip-confirmations', daemon=True).start()
