"""Security audit trail for sensitive OrcAgent actions.

Stores only metadata needed to reconstruct who did what: no private keys, request
bodies, auth tokens or signatures. Client IPs are HMAC-hashed with SECRET_KEY.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time

from flask import g, request

_SENSITIVE_PREFIXES = (
    '/api/admin', '/api/withdraw', '/api/wallet/send', '/api/bridge',
    '/api/trade', '/api/instant-trade', '/api/copy-trade', '/api/groups',
    '/api/messages', '/api/notifications', '/api/wallet/set', '/api/logout',
)
_ID_KEYS = ('id', 'post_id', 'message_id', 'group_id', 'trade_id', 'bridge_id',
            'notification_id', 'user_id', 'peer_id', 'target_user_id')


def _ip_hash() -> str:
    forwarded = (request.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
    value = forwarded or request.remote_addr or ''
    key = str(os.getenv('SECRET_KEY') or 'audit').encode()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()[:24] if value else ''


def _object_ref() -> str:
    parts = []
    try:
        body = request.get_json(silent=True) or {}
    except Exception:
        body = {}
    for key in _ID_KEYS:
        if key in body and body.get(key) not in (None, ''):
            parts.append(f'{key}={str(body.get(key))[:80]}')
    if not parts:
        bits = [b for b in (request.path or '').split('/') if b]
        if bits and bits[-1].isdigit():
            parts.append('path_id=' + bits[-1])
    return ','.join(parts)[:255]


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_audit_hardening_installed', False):
        return
    app._orca_audit_hardening_installed = True
    db_file = dashboard_module.DB_FILE

    conn = sqlite3.connect(db_file)
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS security_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at REAL NOT NULL,
            request_id TEXT NOT NULL,
            user_id INTEGER,
            wallet TEXT,
            method TEXT NOT NULL,
            path TEXT NOT NULL,
            status INTEGER NOT NULL,
            object_ref TEXT,
            ip_hash TEXT,
            user_agent TEXT
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_audit_created ON security_audit_log(created_at)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_audit_wallet ON security_audit_log(wallet, created_at)')
        conn.commit()
    finally:
        conn.close()

    @app.before_request
    def _audit_request_id():
        g.orca_request_id = secrets.token_hex(12)
        path = request.path or ''
        if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            return None
        if not any(path == p or path.startswith(p + '/') for p in _SENSITIVE_PREFIXES):
            return None
        wallet = None
        try:
            fn = getattr(dashboard_module, '_authenticated_wallet', None)
            wallet = fn() if callable(fn) else None
        except Exception:
            wallet = None
        g.orca_audit_wallet = str(wallet or '')
        g.orca_audit_user_id = None
        if wallet:
            try:
                conn = sqlite3.connect(db_file)
                try:
                    row = conn.execute('SELECT id FROM users WHERE wallet_address=? LIMIT 1',
                                       (wallet,)).fetchone()
                    g.orca_audit_user_id = int(row[0]) if row else None
                finally:
                    conn.close()
            except Exception:
                g.orca_audit_user_id = None
        return None

    @app.after_request
    def _audit_sensitive_mutation(response):
        request_id = getattr(g, 'orca_request_id', secrets.token_hex(12))
        response.headers.setdefault('X-Request-ID', request_id)
        if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            return response
        path = request.path or ''
        if not any(path == p or path.startswith(p + '/') for p in _SENSITIVE_PREFIXES):
            return response
        wallet = getattr(g, 'orca_audit_wallet', '') or ''
        user_id = getattr(g, 'orca_audit_user_id', None)
        try:
            conn = sqlite3.connect(db_file, timeout=5)
            try:
                conn.execute('''INSERT INTO security_audit_log
                    (created_at,request_id,user_id,wallet,method,path,status,object_ref,ip_hash,user_agent)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (time.time(), request_id, user_id, str(wallet)[:128],
                     request.method, path[:255], int(response.status_code), _object_ref(),
                     _ip_hash(), str(request.headers.get('User-Agent') or '')[:255]))
                conn.execute('DELETE FROM security_audit_log WHERE created_at < ?',
                             (time.time() - 366 * 86400,))
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            app.logger.warning('security audit write failed request_id=%s: %s', request_id, exc)
        return response
