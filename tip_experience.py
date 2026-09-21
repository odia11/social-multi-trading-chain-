"""Auditable OrcAgent USDC tip receipts and role-scoped history.

No signing, swapping or sending occurs here. A submitted signature is NOT proof
of a confirmed payment; only a chain receipt/status may transition a tip.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from flask import jsonify, request

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = set()
_RECONCILE_LOCK = threading.Lock()
_MAX_PENDING_BATCH = 12
_POLL_SECONDS = 25


def _utcnow():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


@contextmanager
def _db(d):
    conn = sqlite3.connect(d.DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=10000')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _schema(d):
    dbfile = str(d.DB_FILE)
    if dbfile in _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if dbfile in _SCHEMA_READY:
            return
        with _db(d) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS tip_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_user_id INTEGER NOT NULL,
                recipient_user_id INTEGER NOT NULL,
                sender_wallet TEXT NOT NULL,
                recipient_wallet TEXT NOT NULL,
                amount REAL NOT NULL,
                chain TEXT NOT NULL,
                tx_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'submitted',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")
            columns = {r['name'] for r in conn.execute('PRAGMA table_info(tip_transactions)')}
            for name, ddl in (
                ('failure_reason', 'TEXT'),
                ('confirmed_at', 'TEXT'),
                ('notification_sent_at', 'TEXT'),
                ('note', "TEXT NOT NULL DEFAULT ''"),
            ):
                if name not in columns:
                    try:
                        conn.execute(f'ALTER TABLE tip_transactions ADD COLUMN {name} {ddl}')
                    except sqlite3.OperationalError as exc:
                        # Other gunicorn workers may migrate at the same
                        # instant on first startup.
                        if 'duplicate column name' not in str(exc).lower():
                            raise
            conn.execute('CREATE INDEX IF NOT EXISTS idx_tips_sender ON tip_transactions(sender_user_id, created_at)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_tips_recipient ON tip_transactions(recipient_user_id, created_at)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_tips_status ON tip_transactions(status, id)')
            # Legacy code called an RPC submission "confirmed". Reconcile
            # those older rows from the chain; do not count unverified rows in
            # public totals or send duplicate notifications.
            conn.execute("""UPDATE tip_transactions SET status='submitted'
                WHERE status='confirmed' AND confirmed_at IS NULL""")
        _SCHEMA_READY.add(dbfile)


def record_submitted(d, sender_wallet, sender_user_id, recipient_user_id,
                     recipient_wallet, amount, chain, tx_hash, note=''):
    _schema(d)
    note = ''.join(c for c in str(note or '') if c.isprintable()).strip()[:100]
    with _db(d) as conn:
        previous = conn.execute(
            'SELECT id FROM tip_transactions WHERE tx_hash=? AND chain=? LIMIT 1',
            (tx_hash, chain)).fetchone()
        if previous:
            return int(previous['id'])
        cur = conn.execute("""INSERT INTO tip_transactions
            (sender_user_id, recipient_user_id, sender_wallet, recipient_wallet,
             amount, chain, tx_hash, status, note)
             VALUES (?,?,?,?,?,?,?,'submitted',?)""",
            (sender_user_id, recipient_user_id, sender_wallet, recipient_wallet,
             float(amount), chain, tx_hash, note))
        return cur.lastrowid


def _chain_confirmation(d, chain, tx_hash):
    """Return ('confirmed'|'failed', reason) or (None, None) for unknown/pending."""
    if chain == 'solana':
        import portfolio_token_withdraw as tip
        result, _ = tip._rpc_call_any(
            d, 'getSignatureStatuses',
            [[tx_hash], {'searchTransactionHistory': True}])
        value = (result or {}).get('value') if isinstance(result, dict) else None
        status = value[0] if isinstance(value, list) and value else None
        if not status:
            return None, None
        if status.get('err') is not None:
            return 'failed', 'Solana transaction failed on-chain'
        if status.get('confirmationStatus') in ('confirmed', 'finalized'):
            return 'confirmed', None
        return None, None
    if chain in getattr(d, 'EVM_CHAINS', {}):
        w3 = d._get_web3(chain)
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
        except Exception as exc:
            # Web3 often raises TransactionNotFound while a tx is pending.
            # Other transient RPC errors are likewise unknown, never failure.
            if type(exc).__name__ == 'TransactionNotFound':
                return None, None
            raise
        if receipt is None:
            return None, None
        if int(receipt['status']) == 1:
            return 'confirmed', None
        return 'failed', 'Transfer reverted on-chain'
    return None, None


def _transition(d, tip_id, state, reason=None):
    if state not in ('confirmed', 'failed'):
        return False
    _schema(d)
    with _db(d) as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute("""SELECT t.*, u.username AS sender_name
            FROM tip_transactions t LEFT JOIN users u ON u.id=t.sender_user_id
            WHERE t.id=? AND t.status='submitted'""", (tip_id,)).fetchone()
        if not row:
            return False
        cur = conn.execute("""UPDATE tip_transactions SET
            status=?, failure_reason=?, confirmed_at=?
            WHERE id=? AND status='submitted'""",
            (state, (reason or '')[:160] if state == 'failed' else None,
             _utcnow() if state == 'confirmed' else None, tip_id))
        if cur.rowcount != 1:
            return False
        if state == 'confirmed':
            link = f'/wallet?tab=history&tip={tip_id}'
            name = (row['sender_name'] or 'An OrcAgent user')[:70]
            content = f'{name} sent you {float(row["amount"]):.2f} USDC'
            if row['note']:
                content += ' · ' + row['note']
            # Older tips already have a generic notification. Enrich it
            # instead of adding a duplicate.
            old = conn.execute("""SELECT id FROM notifications WHERE
                user_id=? AND type='tip' AND actor_wallet=?
                AND link='/wallet' AND content=?
                ORDER BY id DESC LIMIT 1""",
                (row['recipient_user_id'], row['sender_wallet'],
                 'You received %.2f USDC tip.' % float(row['amount']))).fetchone()
            if old:
                conn.execute('UPDATE notifications SET content=?, link=? WHERE id=?',
                             (content, link, old['id']))
            else:
                conn.execute("""INSERT INTO notifications
                    (user_id,type,content,link,actor_wallet) VALUES (?,?,?,?,?)""",
                    (row['recipient_user_id'], 'tip', content,
                     link, row['sender_wallet']))
            conn.execute('UPDATE tip_transactions SET notification_sent_at=? WHERE id=?',
                         (_utcnow(), tip_id))
    # Push is best-effort, not part of financial confirmation; no duplicate
    # sends because the SQL status transition has a single winner.
    if state == 'confirmed':
        push = getattr(d, '_send_push_notification', None)
        if callable(push):
            try:
                push(row['recipient_user_id'], 'USDC tip received',
                     content, f'/wallet?tab=history&tip={tip_id}')
            except Exception:
                pass
    return True


def _reconcile_one(d, row):
    try:
        state, reason = _chain_confirmation(d, row['chain'], row['tx_hash'])
        if state:
            _transition(d, row['id'], state, reason)
    except Exception:
        # RPC timeouts, 429s and EVM receipt-not-found do not prove failure.
        return


def reconcile_pending(d, limit=_MAX_PENDING_BATCH):
    _schema(d)
    with _db(d) as conn:
        rows = conn.execute("""SELECT id,chain,tx_hash FROM tip_transactions
            WHERE status='submitted' ORDER BY id DESC LIMIT ?""",
            (max(1, min(int(limit), _MAX_PENDING_BATCH)),)).fetchall()
    for row in rows:
        _reconcile_one(d, row)


def _worker(d):
    while True:
        if _RECONCILE_LOCK.acquire(blocking=False):
            try:
                reconcile_pending(d)
            except Exception as exc:
                try:
                    d.app.logger.warning('tip confirmation watch unavailable: %s',
                                         type(exc).__name__)
                except Exception:
                    pass
            finally:
                _RECONCILE_LOCK.release()
        time.sleep(_POLL_SECONDS)


def _identity(d):
    wallet = d._authenticated_wallet()
    if not wallet:
        return None
    with _db(d) as conn:
        row = conn.execute('SELECT id FROM users WHERE wallet_address=? LIMIT 1',
                           (wallet,)).fetchone()
    return int(row['id']) if row else None


def _format_tip(row, me=None):
    v = dict(row)
    sent = me == v['sender_user_id'] if me is not None else None
    return {
        'id': v['id'], 'amount': v['amount'], 'currency': 'USDC',
        'message': v.get('note') or '',
        'chain': v['chain'], 'status': v['status'],
        'failure_reason': v.get('failure_reason') if me is not None else None,
        'sender_user_id': v['sender_user_id'],
        'recipient_user_id': v['recipient_user_id'],
        'sender_username': v.get('sender_username') or 'OrcAgent user',
        'recipient_username': v.get('recipient_username') or 'OrcAgent user',
        'sender_profile': '/profile/' + (v.get('sender_profile_wallet') or ''),
        'recipient_profile': '/profile/' + (v.get('recipient_profile_wallet') or ''),
        'direction': ('sent' if sent else 'received') if me is not None else None,
        'created_at': v['created_at'], 'confirmed_at': v.get('confirmed_at'),
        'explorer_url': __import__('portfolio_token_withdraw')._explorer(v['chain'], v['tx_hash']),
        'tx_hash': v['tx_hash'],
    }


_TIP_SELECT = """SELECT t.*,
    s.username AS sender_username, r.username AS recipient_username,
    s.wallet_address AS sender_profile_wallet,
    r.wallet_address AS recipient_profile_wallet
    FROM tip_transactions t
    LEFT JOIN users s ON s.id=t.sender_user_id
    LEFT JOIN users r ON r.id=t.recipient_user_id"""


def install(d):
    app = d.app
    if getattr(app, '_orca_tip_experience_installed', False):
        return
    _schema(d)
    app._orca_tip_experience_installed = True

    @app.get('/api/tips/mine')
    def tips_mine():
        me = _identity(d)
        if me is None:
            return jsonify({'ok': False, 'error': 'Authentication required'}), 401
        role = str(request.args.get('role') or 'all').lower()
        if role not in ('all', 'sent', 'received'):
            return jsonify({'ok': False, 'error': 'Invalid tip direction'}), 400
        try:
            limit = max(1, min(int(request.args.get('limit', 30)), 100))
        except (ValueError, TypeError):
            limit = 30
        where = ('t.sender_user_id=?' if role == 'sent' else
                 't.recipient_user_id=?' if role == 'received' else
                 '(t.sender_user_id=? OR t.recipient_user_id=?)')
        params = (me,) if role != 'all' else (me, me)
        with _db(d) as conn:
            rows = conn.execute(_TIP_SELECT +
                f' WHERE {where} ORDER BY t.id DESC LIMIT ?',
                (*params, limit)).fetchall()
        # Recheck only the newest handful synchronously. The durable worker
        # handles older pending receipts; a history screen must not spend
        # minutes making 100 sequential RPC calls on a slow provider.
        for row in rows[:3]:
            if row['status'] == 'submitted':
                _reconcile_one(d, row)
        with _db(d) as conn:
            rows = conn.execute(_TIP_SELECT +
                f' WHERE {where} ORDER BY t.id DESC LIMIT ?',
                (*params, limit)).fetchall()
        return jsonify({'ok': True, 'tips': [_format_tip(r, me) for r in rows]})

    @app.get('/api/tips/<int:tip_id>')
    def tip_detail(tip_id):
        me = _identity(d)
        if me is None:
            return jsonify({'ok': False, 'error': 'Authentication required'}), 401
        with _db(d) as conn:
            row = conn.execute(_TIP_SELECT + ' WHERE t.id=? AND '
                '(t.sender_user_id=? OR t.recipient_user_id=?)',
                (tip_id, me, me)).fetchone()
        if not row:
            return jsonify({'ok': False, 'error': 'Tip not found'}), 404
        if row['status'] == 'submitted':
            _reconcile_one(d, row)
            with _db(d) as conn:
                row = conn.execute(_TIP_SELECT + ' WHERE t.id=?',
                                   (tip_id,)).fetchone()
        return jsonify({'ok': True, 'tip': _format_tip(row, me)})

    @app.get('/api/profile/<int:user_id>/tip-stats')
    def profile_tip_stats(user_id):
        _schema(d)
        me = _identity(d)
        with _db(d) as conn:
            user = conn.execute('SELECT id FROM users WHERE id=?', (user_id,)).fetchone()
            if not user:
                return jsonify({'ok': False, 'error': 'Profile not found'}), 404
            stats = conn.execute("""SELECT COALESCE(SUM(amount),0),
                COUNT(DISTINCT sender_user_id), COUNT(*)
                FROM tip_transactions WHERE recipient_user_id=? AND status='confirmed'""",
                (user_id,)).fetchone()
            result = {'ok': True, 'user_id': user_id,
                      'received_usdc': round(float(stats[0]), 6),
                      'supporters': int(stats[1]), 'received_count': int(stats[2])}
            if me == user_id:
                sent = conn.execute("""SELECT COALESCE(SUM(amount),0)
                    FROM tip_transactions WHERE sender_user_id=?
                    AND status='confirmed'""", (me,)).fetchone()
                result['sent_usdc'] = round(float(sent[0]), 6)
        return jsonify(result)

    # Each gunicorn worker can restart independently. The persistent SQL
    # conditional transition makes multiple reconcilers safe and avoids lost
    # pending tips across restarts.
    threading.Thread(target=_worker, args=(d,), name='orca-tip-confirmations',
                     daemon=True).start()
