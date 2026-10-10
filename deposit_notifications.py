"""Confirmed deposits: durable inbox entries, push outbox and offline scanning."""
import hashlib
import math
import sqlite3
import threading
import time
from flask import request
from portfolio_wallet_activity import _wallet_events

_PUSH_LOCK = threading.Lock()
_RECENT_SECONDS = 24 * 60 * 60


def _schema(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS deposit_watch (user_id INTEGER PRIMARY KEY, since REAL NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS deposit_notice (user_id INTEGER, event_id TEXT, PRIMARY KEY(user_id,event_id))')
    conn.execute('''CREATE TABLE IF NOT EXISTS deposit_push_queue (
        user_id INTEGER NOT NULL, event_id TEXT NOT NULL, content TEXT NOT NULL,
        dispatched INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id,event_id))''')


def _register_wallets(d, now):
    # Watch every managed wallet, including members who have never opened
    # Notifications. Persist a baseline before scanning; restarts retain it.
    with sqlite3.connect(d.DB_FILE, timeout=8) as conn:
        conn.execute('''INSERT OR IGNORE INTO deposit_watch(user_id,since)
            SELECT id, MAX(?, COALESCE(CAST(strftime('%s',created_at) AS REAL),?))
            FROM users WHERE COALESCE(encrypted_private_key,'')<>'' ''',
            (now-_RECENT_SECONDS, now))


def _dispatch_pending(d):
    send = getattr(d, '_send_push_notification', None)
    if not callable(send) or not _PUSH_LOCK.acquire(blocking=False):
        return
    try:
        with sqlite3.connect(d.DB_FILE, timeout=8) as conn:
            rows = conn.execute('SELECT user_id,event_id,content FROM deposit_push_queue WHERE dispatched=0 LIMIT 20').fetchall()
            for uid, event_id, content in rows:
                tag = 'deposit-'+hashlib.sha256(event_id.encode()).hexdigest()[:24]
                try:
                    send(uid, 'Funds received', content, '/wallet?tab=history', tag=tag)
                except Exception as exc:
                    d.app.logger.warning('Deposit push dispatch unavailable (%s)', type(exc).__name__)
                    continue
                conn.execute('UPDATE deposit_push_queue SET dispatched=1 WHERE user_id=? AND event_id=?', (uid,event_id))
    finally:
        _PUSH_LOCK.release()


def record(d, wallet, events, started):
    conn = sqlite3.connect(d.DB_FILE, timeout=8)
    fresh_count = 0
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            user = conn.execute('SELECT id FROM users WHERE wallet_address=?', (wallet,)).fetchone()
            if not user:
                return 0
            conn.execute('INSERT OR IGNORE INTO deposit_watch VALUES (?,?)', (user[0], started))
            since = conn.execute('SELECT since FROM deposit_watch WHERE user_id=?', (user[0],)).fetchone()[0]
            for event in events:
                if event.get('type') != 'receive' or event.get('status') != 'confirmed':
                    continue
                try:
                    timestamp = float(event.get('timestamp') or 0)
                    amount = float(event.get('amount') or 0)
                except (TypeError, ValueError):
                    continue
                event_id = str(event.get('id') or '')
                if not event_id or timestamp < since or not math.isfinite(amount) or not math.isfinite(timestamp) or amount <= 0:
                    continue
                fresh = conn.execute('INSERT OR IGNORE INTO deposit_notice VALUES (?,?)', (user[0], event_id)).rowcount
                if fresh:
                    content = 'You received %.9g %s' % (amount, str(event.get('currency') or 'tokens')[:32])
                    conn.execute('INSERT INTO notifications (user_id,type,content,link) VALUES (?,?,?,?)',
                        (user[0], 'deposit', content, '/wallet?tab=history'))
                    conn.execute('INSERT OR IGNORE INTO deposit_push_queue(user_id,event_id,content) VALUES (?,?,?)',
                        (user[0], event_id, content))
                    fresh_count += 1
    finally:
        conn.close()
    # Clear only this user's holdings cache. The next portfolio read must
    # fetch the confirmed deposit rather than redisplay the previous snapshot.
    if fresh_count:
        cache = getattr(d, '_wallet_tokens_cache', None)
        if isinstance(cache, dict):
            cache.pop(wallet, None)
    _dispatch_pending(d)
    return fresh_count


def install(d):
    if getattr(d.app, '_deposit_notifications_installed', False):
        return
    d.app._deposit_notifications_installed = True
    with sqlite3.connect(d.DB_FILE) as conn:
        _schema(conn)
    _register_wallets(d, time.time())
    guard = threading.Lock()
    capacity = threading.BoundedSemaphore(2)
    checked = {}
    running = set()

    def run(wallet, started):
        try:
            record(d, wallet, [], started)
            with sqlite3.connect(d.DB_FILE, timeout=8) as conn:
                since = conn.execute('''SELECT w.since FROM deposit_watch w
                    JOIN users u ON u.id=w.user_id WHERE u.wallet_address=?''', (wallet,)).fetchone()[0]
            record(d, wallet, _wallet_events(d, wallet, since=since), started)
        except Exception as exc:
            # Report only the class, never RPC URLs, credentials or wallet data.
            d.app.logger.warning('Deposit check temporarily unavailable (%s)', type(exc).__name__)
        finally:
            with guard:
                running.discard(wallet)
            capacity.release()

    def queue(wallet, now):
        with guard:
            if wallet in running or now - checked.get(wallet, 0) < 30 or not capacity.acquire(blocking=False):
                return False
            checked[wallet] = now
            running.add(wallet)
            if len(checked) > 10000:
                for key in list(checked):
                    if key not in running and checked[key] < now - 300:
                        checked.pop(key, None)
        threading.Thread(target=run, args=(wallet, now), daemon=True, name='deposit-check').start()
        return True

    @d.app.before_request
    def schedule():
        if request.method != 'GET' or request.path not in (
                '/api/notifications/mine', '/api/notifications/mine/unread_count',
                '/api/portfolio/wallet-activity', '/api/portfolio/snapshot'):
            return
        wallet = d._authenticated_wallet()
        if wallet:
            queue(wallet, time.time())

    def watch():
        cursor = 0
        while True:
            time.sleep(5)
            try:
                now = time.time()
                _register_wallets(d, now)
                _dispatch_pending(d)
                with sqlite3.connect(d.DB_FILE, timeout=8) as conn:
                    rows = conn.execute('''SELECT u.id,u.wallet_address FROM deposit_watch w
                        JOIN users u ON u.id=w.user_id WHERE u.id>? ORDER BY u.id LIMIT 10''', (cursor,)).fetchall()
                if not rows:
                    cursor = 0
                    continue
                for uid, wallet in rows:
                    # Advance only after a wallet is already current or queued.
                    # When capacity is full, retry this wallet next cycle.
                    with guard:
                        current = wallet in running or now-checked.get(wallet,0) < 30
                    if current or queue(wallet, now):
                        cursor = uid
                    else:
                        break
            except Exception as exc:
                d.app.logger.warning('Deposit watcher temporarily unavailable (%s)', type(exc).__name__)
    threading.Thread(target=watch, daemon=True, name='deposit-watcher').start()
