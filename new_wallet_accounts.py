"""Guest wallet accounts; existing signature/password authentication is unchanged.

Pending keypairs live only in this worker and expire after ten minutes. Deploy
with one worker (threads are safe); restarting invalidates unconfirmed wallets.
Import is browser-local signing, not a private-key upload endpoint.
"""
from __future__ import annotations

from collections import deque
from contextlib import closing
import hashlib
import re
import secrets
import sqlite3
import threading
import time

import bcrypt
from flask import jsonify, request, session
from solders.keypair import Keypair

START = '/api/account/create-wallet/start'
CONFIRM = '/api/account/create-wallet/confirm'
TTL = 600


def valid_key_export(payload):
    """Fail closed unless this is the exact one-time wallet creation payload."""
    try:
        if not isinstance(payload, dict) or set(payload) != {'ok', 'address', 'private_key', 'token'} or payload['ok'] is not True:
            return False
        return (isinstance(payload['token'], str) and len(payload['token']) >= 32
                and str(Keypair.from_base58_string(payload['private_key']).pubkey()) == payload['address'])
    except Exception:
        return False


def install(d):
    app = d.app
    if getattr(app, '_orca_new_wallet_accounts_installed', False):
        return
    app._orca_new_wallet_accounts_installed = True
    pending, attempts = {}, {}
    lock = threading.Lock()

    def prune(now):
        for token in list(pending):
            if pending[token][0] <= now:
                del pending[token]
        for ip in list(attempts):
            while attempts[ip] and attempts[ip][0] <= now - 3600:
                attempts[ip].popleft()
            if not attempts[ip]:
                del attempts[ip]

    def expire():
        while True:
            time.sleep(60)
            with lock:
                prune(time.monotonic())

    threading.Thread(target=expire, name='new-wallet-expiry', daemon=True).start()

    def response(payload, status=200):
        resp = jsonify(payload)
        resp.status_code = status
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp

    def error(message, status):
        return response({'ok': False, 'error': message}, status)

    def guard():
        if d._authenticated_wallet():
            return error('Already signed in', 409)
        # Also require a guest CSRF token: obtain it via /api/csrf-token.
        if not d._validate_csrf(request.headers.get('X-CSRF-Token', '')):
            return error('CSRF validation failed', 403)
        return None

    @app.post(START)
    def new_wallet_start():
        denied = guard()
        if denied is not None:
            return denied
        # remote_addr is the deployment's configured proxy identity. Do not
        # trust an arbitrary client-supplied X-Real-IP / X-Forwarded-For.
        ip = request.remote_addr or 'unknown'
        now = time.monotonic()
        with lock:
            prune(now)
            hits = attempts.setdefault(ip, deque())
            if len(hits) >= 3:
                return error('Too many wallet creation attempts. Try again in an hour.', 429)
            if len(pending) >= 1000 or len(attempts) >= 10000:
                return error('Wallet creation is busy. Try again later.', 503)
            hits.append(now)
            keypair = Keypair()
            token = secrets.token_urlsafe(32)
            owner = session.setdefault('new_wallet_owner', secrets.token_urlsafe(32))
            pending[token] = (now + TTL, owner, keypair)
        return response({'ok': True, 'address': str(keypair.pubkey()),
                         'private_key': str(keypair), 'token': token})

    @app.post(CONFIRM)
    def new_wallet_confirm():
        denied = guard()
        if denied is not None:
            return denied
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return error('JSON object required', 400)
        token = body.get('token')
        if not isinstance(token, str) or len(token) > 128:
            return error('Invalid or expired wallet token. Create a new wallet.', 400)
        with lock:
            prune(time.monotonic())
            item = pending.get(token)
            owner = session.get('new_wallet_owner', '')
            if item is None or not owner or not secrets.compare_digest(item[1], owner):
                return error('Invalid or expired wallet token. Create a new wallet.', 400)
            # Atomically claim once, including when subsequent validation fails.
            del pending[token]
        if body.get('confirmed_backup') is not True:
            return error('Confirm that you saved your private key. Create a new wallet to retry.', 400)
        username = body.get('username')
        password = body.get('password')
        if not isinstance(username, str) or not isinstance(password, str):
            return error('Username and password required. Create a new wallet to retry.', 400)
        username, password = username.strip(), password.strip()
        # Same character, length and case-insensitive uniqueness rules as /api/username.
        if not username or len(username) > 20 or not re.fullmatch(r'[a-zA-Z0-9_]+', username):
            return error('Username must use 1–20 letters, numbers or underscores. Create a new wallet to retry.', 400)
        if len(password) < 10 or len(password.encode('utf-8')) > 72:
            return error('Password must have at least 10 characters and at most 72 UTF-8 bytes. Create a new wallet to retry.', 400)
        keypair = item[2]
        address, private_key = str(keypair.pubkey()), str(keypair)
        try:
            encrypted = d.encrypt_private_key(private_key, address)
            key_hash = hashlib.sha256(private_key.encode()).hexdigest()
            password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
            with closing(sqlite3.connect(d.DB_FILE, timeout=10)) as conn, conn:
                conn.execute('BEGIN IMMEDIATE')
                if conn.execute('SELECT 1 FROM users WHERE username=? COLLATE NOCASE', (username,)).fetchone():
                    return error('Username already taken. Create a new wallet to retry.', 409)
                # Never overwrite an existing identity's credentials, even in
                # the astronomically unlikely event of a public-key collision.
                if conn.execute('SELECT 1 FROM users WHERE wallet_address=?', (address,)).fetchone():
                    return error('Wallet already registered. Create a new wallet to retry.', 409)
                user_id = d.get_or_create_user(address, connection=conn)
                if not user_id:
                    raise RuntimeError('User creation failed')
                conn.execute('UPDATE users SET encrypted_private_key=?, key_hash=?, password_hash=?, username=? WHERE id=?',
                             (encrypted, key_hash, password_hash, username, user_id))
        except Exception:
            # No exception values or payloads: they may contain key material.
            app.logger.error('new wallet account activation failed')
            return error('Could not activate account. Create a new wallet to retry.', 503)
        finally:
            private_key = password = ''
            keypair = item = None

        # Establish the same identity/session/device as signed wallet login,
        # with a fresh CSRF token and no data from a previous readonly session.
        session.clear()
        session.permanent = True
        session['wallet'] = address
        session['user_id'] = user_id
        csrf_token = d._get_csrf_token()
        d.get_user_state(address)['has_trading_key'] = True
        device_token = d._issue_device_token(user_id, address)
        resp = response({'ok': True, 'success': True, 'wallet': address,
                         'username': username, 'has_trading_key': True,
                         'csrf_token': csrf_token, 'device_token': device_token,
                         'redirect': '/dashboard'})
        return d._set_device_cookie(resp, device_token)

    @app.after_request
    def new_wallet_assets(resp):
        if request.path in {START, CONFIRM}:
            resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
        if resp.mimetype != 'text/html':
            return resp
        html = resp.get_data(as_text=True)
        if '</head>' in html and '/static/new-wallet.css' not in html:
            html = html.replace('</head>', '<link rel="stylesheet" href="/static/new-wallet.css?v=1"></head>', 1)
        if '</body>' in html and '/static/new-wallet.js' not in html:
            vendor = '' if '/static/vendor/tweetnacl-1.0.3.min.js' in html else '<script src="/static/vendor/tweetnacl-1.0.3.min.js" defer></script>'
            html = html.replace('</body>', vendor + '<script src="/static/new-wallet.js?v=1" defer></script></body>', 1)
        resp.set_data(html)
        return resp
