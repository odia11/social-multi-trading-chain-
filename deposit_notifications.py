"""Read-only deposit checks for active sessions; durable notification deduplication."""
import sqlite3
import threading
import time
from flask import request
from portfolio_wallet_activity import _wallet_events


def record(d, wallet, events, started):
    conn = sqlite3.connect(d.DB_FILE, timeout=8)
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            user = conn.execute('SELECT id FROM users WHERE wallet_address=?', (wallet,)).fetchone()
            if not user:
                return
            conn.execute('INSERT OR IGNORE INTO deposit_watch VALUES (?,?)', (user[0], started))
            since = conn.execute('SELECT since FROM deposit_watch WHERE user_id=?', (user[0],)).fetchone()[0]
            for event in events:
                if event.get('type') != 'receive' or event.get('status') != 'confirmed' or event.get('timestamp', 0) < since:
                    continue
                fresh = conn.execute('INSERT OR IGNORE INTO deposit_notice VALUES (?,?)', (user[0], event['id'])).rowcount
                if fresh:
                    conn.execute('INSERT INTO notifications (user_id,type,content,link) VALUES (?,?,?,?)',
                        (user[0], 'deposit', 'You received %.9g %s' % (event['amount'], event['currency']), '/wallet?tab=history'))
    finally:
        conn.close()


def install(d):
    if getattr(d.app, '_deposit_notifications_installed', False):
        return
    d.app._deposit_notifications_installed = True
    with sqlite3.connect(d.DB_FILE) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS deposit_watch (user_id INTEGER PRIMARY KEY, since REAL NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS deposit_notice (user_id INTEGER, event_id TEXT, PRIMARY KEY(user_id,event_id))')
    guard = threading.Lock()
    capacity = threading.BoundedSemaphore(2)
    checked = {}

    def run(wallet, started):
        try:
            # Persist baseline before RPC; failed reads cannot reset the baseline.
            record(d, wallet, [], started)
            record(d, wallet, _wallet_events(d, wallet), started)
        except Exception:
            d.app.logger.warning('Deposit check temporarily unavailable')
        finally:
            capacity.release()

    @d.app.before_request
    def schedule():
        if request.path != '/api/notifications/mine' or request.method != 'GET':
            return
        wallet = d._authenticated_wallet()
        if not wallet:
            return
        now = time.time()
        with guard:
            if now - checked.get(wallet, 0) < 30 or not capacity.acquire(blocking=False):
                return
            checked[wallet] = now
            if len(checked) > 10000:
                for key in list(checked):
                    if checked[key] < now - 300:
                        checked.pop(key, None)
        threading.Thread(target=run, args=(wallet, now), daemon=True, name='deposit-check').start()

    def watch():
        cursor = 0
        while True:
            time.sleep(15)
            try:
                with sqlite3.connect(d.DB_FILE, timeout=8) as conn:
                    rows = conn.execute('SELECT u.id,u.wallet_address FROM deposit_watch w JOIN users u ON u.id=w.user_id WHERE u.id>? ORDER BY u.id LIMIT 2', (cursor,)).fetchall()
                if not rows:
                    cursor = 0
                    continue
                for uid, wallet in rows:
                    cursor = uid
                    now = time.time()
                    with guard:
                        if now - checked.get(wallet, 0) < 30 or not capacity.acquire(blocking=False):
                            continue
                        checked[wallet] = now
                    threading.Thread(target=run, args=(wallet, now), daemon=True, name='deposit-check').start()
            except Exception:
                d.app.logger.warning('Deposit watcher temporarily unavailable')
    threading.Thread(target=watch, daemon=True, name='deposit-watcher').start()
