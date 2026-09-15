"""Replay protection for wallet sign-in challenges.

The existing login chain already verifies the signed message and stores server-issued
nonces in auth_nonces. This layer adds an atomic one-time claim before /api/wallet/set
is allowed to consume a login challenge, so two concurrent/replayed submissions can
never both reach the login handler. Empty-address logout calls are intentionally
left alone because they are not authentication attempts.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
import time

from flask import jsonify, request

_NONCE_TTL_SECONDS = 600


def _parse_created_at(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f'):
        try:
            dt = _dt.datetime.strptime(text.replace('Z', ''), fmt)
            return dt.replace(tzinfo=_dt.timezone.utc).timestamp()
        except ValueError:
            continue
    try:
        dt = _dt.datetime.fromisoformat(text.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_auth_replay_hardening_installed', False):
        return
    app._orca_auth_replay_hardening_installed = True

    db_file = dashboard_module.DB_FILE
    conn = sqlite3.connect(db_file)
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS auth_nonce_claims (
            nonce TEXT PRIMARY KEY,
            claimed_at REAL NOT NULL
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_auth_nonce_claims_time ON auth_nonce_claims(claimed_at)')
        conn.commit()
    finally:
        conn.close()

    @app.before_request
    def _claim_wallet_login_nonce_once():
        if request.method != 'POST' or request.path != '/api/wallet/set':
            return None
        body = request.get_json(silent=True) or {}
        address = str(body.get('address') or '').strip()
        # Deliberate Disconnect/Logout uses the same endpoint with an empty address.
        if not address:
            return None
        nonce = str(body.get('nonce') or '').strip()
        if not nonce or len(nonce) > 256:
            return jsonify({'ok': False, 'error': 'Invalid or missing login challenge'}), 400

        now = time.time()
        conn = sqlite3.connect(db_file, timeout=10)
        try:
            conn.execute('BEGIN IMMEDIATE')
            # Keep the claim table bounded without weakening replay protection.
            conn.execute('DELETE FROM auth_nonce_claims WHERE claimed_at < ?',
                         (now - 24 * 3600,))
            row = conn.execute('SELECT created_at FROM auth_nonces WHERE nonce=? LIMIT 1',
                               (nonce,)).fetchone()
            if not row:
                conn.rollback()
                return jsonify({'ok': False, 'error': 'Login challenge is invalid or already used'}), 401
            created = _parse_created_at(row[0])
            if created is None or created > now + 30 or now - created > _NONCE_TTL_SECONDS:
                # Expired challenges are deleted so they cannot later become valid again.
                conn.execute('DELETE FROM auth_nonces WHERE nonce=?', (nonce,))
                conn.commit()
                return jsonify({'ok': False, 'error': 'Login challenge expired'}), 401
            try:
                conn.execute('INSERT INTO auth_nonce_claims(nonce, claimed_at) VALUES (?,?)',
                             (nonce, now))
                conn.commit()
            except sqlite3.IntegrityError:
                conn.rollback()
                return jsonify({'ok': False, 'error': 'Login challenge already used'}), 409
        finally:
            conn.close()
        return None
