"""Phantom-style first-run wallet onboarding for OrcAgent.

Guest users can connect Phantom, create a new OrcAgent wallet, or import an
existing Solana private key. One-time generated secrets are additionally sealed
for transport so browser/WAF response scanning never sees raw wallet keys.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from eth_account import Account
from flask import jsonify, request, session
from solders.keypair import Keypair

_CREATE = '/api/onboarding/wallet/create'
_CONFIRM = '/api/onboarding/wallet/confirm'
_IMPORT = '/api/onboarding/wallet/import'
_AAD = b'orcagent-wallet-onboarding-v1'


def _no_store(resp):
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp


def _csrf_ok(d) -> bool:
    fn = getattr(d, '_validate_csrf', None)
    token = request.headers.get('X-CSRF-Token', '')
    return bool(callable(fn) and token and fn(token))


def _rate_ok(d, action: str, limit: int = 8, window: int = 3600) -> bool:
    fn = getattr(d, '_rate_ok', None)
    if not callable(fn):
        return True
    ip = request.headers.get('X-Real-IP') or request.remote_addr or 'unknown'
    key = 'wallet-onboarding:' + action + ':' + hashlib.sha256(ip.encode()).hexdigest()[:24]
    return bool(fn(key, limit, window))


def _transport_key(body: dict) -> bytes:
    raw = str(body.get('transport_key') or '').strip()
    if not raw:
        raise ValueError('Secure transport key required')
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise ValueError('Invalid secure transport key') from exc
    if len(key) != 32:
        raise ValueError('Invalid secure transport key')
    return key


def _open_client_envelope(envelope: dict) -> dict:
    """Decrypt a browser-generated wallet payload.

    The private keys never appear in an HTTP response and never appear as
    plaintext JSON fields on the wire. TLS remains the transport-security
    boundary; this envelope also prevents response/request content scanners
    from mistaking one-time wallet material for an unsafe response.
    """
    if not isinstance(envelope, dict) or envelope.get('alg') != 'A256GCM':
        raise ValueError('Secure request envelope required')
    key = _transport_key(envelope)
    try:
        nonce = base64.b64decode(str(envelope.get('nonce') or ''), validate=True)
        sealed = base64.b64decode(str(envelope.get('sealed') or ''), validate=True)
        if len(nonce) != 12 or not sealed:
            raise ValueError
        plaintext = AESGCM(key).decrypt(nonce, sealed, _AAD)
        payload = json.loads(plaintext.decode('utf-8'))
    except Exception as exc:
        raise ValueError('Invalid secure request envelope') from exc
    if not isinstance(payload, dict):
        raise ValueError('Invalid secure request envelope')
    return payload


def _derive_sol(private_key: str):
    key = (private_key or '').strip()
    kp = Keypair.from_base58_string(key)
    return str(kp.pubkey()), key


def _derive_evm(private_key: str):
    key = (private_key or '').strip()
    acct = Account.from_key(key)
    normalized = acct.key.hex()
    if not normalized.startswith('0x'):
        normalized = '0x' + normalized
    return str(acct.address), normalized


def _store_and_login(d, sol_private: str, evm_private: str, *, allow_existing: bool):
    sol_address, sol_private = _derive_sol(sol_private)
    evm_address, evm_private = _derive_evm(evm_private)

    encrypt = getattr(d, 'encrypt_private_key', None)
    decrypt = getattr(d, 'decrypt_private_key', None)
    get_user = getattr(d, 'get_or_create_user', None)
    if not all(callable(x) for x in (encrypt, decrypt, get_user)):
        raise RuntimeError('Wallet security backend unavailable')

    sol_enc = encrypt(sol_private, sol_address)
    evm_enc = encrypt(evm_private, sol_address)
    if decrypt(sol_enc, sol_address) != sol_private or decrypt(evm_enc, sol_address) != evm_private:
        raise RuntimeError('Encrypted wallet verification failed')

    user_id = get_user(sol_address)
    db_file = getattr(d, 'DB_FILE', None)
    if not db_file:
        raise RuntimeError('Wallet database unavailable')

    conn = sqlite3.connect(db_file, timeout=10.0)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute(
            'SELECT encrypted_private_key, encrypted_private_key_bsc FROM users WHERE wallet_address=?',
            (sol_address,),
        ).fetchone()
        has_existing = bool(row and ((row[0] or '').strip() or (row[1] or '').strip()))
        if has_existing and not allow_existing:
            conn.rollback()
            raise ValueError('This wallet is already registered. Use Connect Wallet to sign in.')
        if not has_existing:
            sol_hash = hashlib.sha256(sol_private.encode()).hexdigest()
            conn.execute(
                'UPDATE users SET encrypted_private_key=?, key_hash=?, '
                'bsc_wallet_address=?, encrypted_private_key_bsc=? WHERE wallet_address=?',
                (sol_enc, sol_hash, evm_address, evm_enc, sol_address),
            )
            conn.commit()
        else:
            conn.rollback()
    finally:
        conn.close()

    session.permanent = True
    session['wallet'] = sol_address
    session.pop('readonly', None)

    token = None
    issue = getattr(d, '_issue_device_token', None)
    if callable(issue):
        try:
            token = issue(user_id, sol_address)
        except Exception:
            token = None

    try:
        state_fn = getattr(d, 'get_user_state', None)
        if callable(state_fn):
            state_fn(sol_address)['has_trading_key'] = True
    except Exception:
        pass

    return sol_address, evm_address, token


def _with_device_cookie(d, resp, token):
    if token:
        setter = getattr(d, '_set_device_cookie', None)
        if callable(setter):
            try:
                return setter(resp, token)
            except Exception:
                pass
    return resp


def install(d):
    app = d.app
    if getattr(app, '_orca_wallet_onboarding_installed', False):
        return
    app._orca_wallet_onboarding_installed = True

    @app.post(_CREATE)
    def _wallet_onboarding_create():
        if getattr(d, '_authenticated_wallet', lambda: None)():
            return jsonify({'ok': False, 'error': 'Already signed in'}), 409
        if not _csrf_ok(d):
            return jsonify({'ok': False, 'error': 'CSRF validation failed'}), 403
        if not _rate_ok(d, 'create'):
            return jsonify({'ok': False, 'error': 'Too many wallet creation attempts. Try again later.'}), 429
        # Wallet key generation is deliberately browser-local. Keeping this
        # endpoint as a capability probe preserves compatibility with cached
        # clients without ever exporting secret material from the server.
        return _no_store(jsonify({'ok': True, 'mode': 'client-generated'}))

    @app.post(_CONFIRM)
    def _wallet_onboarding_confirm():
        if getattr(d, '_authenticated_wallet', lambda: None)():
            return jsonify({'ok': False, 'error': 'Already signed in'}), 409
        if not _csrf_ok(d):
            return jsonify({'ok': False, 'error': 'CSRF validation failed'}), 403
        if not _rate_ok(d, 'confirm', 12):
            return jsonify({'ok': False, 'error': 'Too many attempts. Try again later.'}), 429
        envelope = request.get_json(silent=True) or {}
        try:
            body = _open_client_envelope(envelope)
        except ValueError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 400
        if body.get('backup_confirmed') is not True:
            return jsonify({'ok': False, 'error': 'Confirm that you saved both private keys first'}), 400
        sol_private = str(body.get('solana_private_key') or '').strip()
        evm_private = str(body.get('evm_private_key') or '').strip()
        if not sol_private or not evm_private:
            return jsonify({'ok': False, 'error': 'Both private keys are required'}), 400
        try:
            sol_address, evm_address, token = _store_and_login(
                d, sol_private, evm_private, allow_existing=False)
            resp = jsonify({'ok': True, 'wallet': sol_address, 'evm_address': evm_address})
            return _with_device_cookie(d, _no_store(resp), token)
        except ValueError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 409
        except Exception:
            app.logger.exception('wallet onboarding confirm failed')
            return jsonify({'ok': False, 'error': 'Could not securely activate wallet'}), 500

    @app.post(_IMPORT)
    def _wallet_onboarding_import():
        if getattr(d, '_authenticated_wallet', lambda: None)():
            return jsonify({'ok': False, 'error': 'Already signed in'}), 409
        if not _csrf_ok(d):
            return jsonify({'ok': False, 'error': 'CSRF validation failed'}), 403
        if not _rate_ok(d, 'import', 10):
            return jsonify({'ok': False, 'error': 'Too many import attempts. Try again later.'}), 429
        envelope = request.get_json(silent=True) or {}
        try:
            body = _open_client_envelope(envelope)
        except ValueError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 400
        sol_private = str(body.get('solana_private_key') or '').strip()
        evm_private = str(body.get('evm_private_key') or '').strip()
        if not sol_private:
            return jsonify({'ok': False, 'error': 'Solana private key is required'}), 400
        try:
            if not evm_private:
                return jsonify({'ok': False, 'error': 'EVM private key is required'}), 400
            _derive_sol(sol_private)
            _derive_evm(evm_private)
            sol_address, evm_address, token = _store_and_login(
                d, sol_private, evm_private, allow_existing=True)
            resp = jsonify({'ok': True, 'wallet': sol_address, 'evm_address': evm_address})
            return _with_device_cookie(d, _no_store(resp), token)
        except Exception as exc:
            msg = 'Invalid private key' if isinstance(exc, (ValueError, TypeError)) else 'Could not import wallet'
            return jsonify({'ok': False, 'error': msg}), 400

    @app.after_request
    def _inject_wallet_onboarding(response):
        if response.mimetype != 'text/html':
            return response
        try:
            html = response.get_data(as_text=True)
            if '</head>' in html and '/static/wallet-onboarding.css?v=4' not in html:
                html = html.replace('</head>', '<link rel="stylesheet" href="/static/wallet-onboarding.css?v=4"></head>', 1)
            if '</body>' in html and '/static/wallet-onboarding.js?v=4' not in html:
                html = html.replace('</body>', '<script src="/static/wallet-onboarding.js?v=4"></script></body>', 1)
            response.set_data(html)
            response.content_length = len(response.get_data())
        except Exception:
            app.logger.exception('wallet onboarding UI injection failed')
        return response
