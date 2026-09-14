"""Generate dedicated OrcAgent trading wallets and save them only after backup confirmation.

The authenticated wallet remains the user's OrcAgent identity. This feature creates:
- one Solana ed25519 trading wallet;
- one EVM secp256k1 trading wallet reused on BSC/Base/Arbitrum/Polygon/etc.

Generation does NOT persist private keys. The browser receives them once, the user
must confirm they saved both, and only then sends them back over HTTPS to be stored
using dashboard.py's existing wallet-bound double-Fernet encryption. No plaintext
key is logged and API responses are explicitly no-store.
"""
from __future__ import annotations

import hashlib
import sqlite3

from flask import jsonify, request
from solders.keypair import Keypair
from eth_account import Account

_GENERATE_PATH = '/api/wallet/generate-trading-wallet'
_CONFIRM_PATH = '/api/wallet/generated/confirm'


def _csrf_ok(dashboard_module) -> bool:
    token = request.headers.get('X-CSRF-Token', '')
    fn = getattr(dashboard_module, '_validate_csrf', None)
    return bool(callable(fn) and fn(token))


def _auth_wallet(dashboard_module):
    fn = getattr(dashboard_module, '_authenticated_wallet', None)
    try:
        value = fn() if callable(fn) else None
    except Exception:
        value = None
    return str(value) if value else None


def _rate_ok(dashboard_module, wallet: str, action: str, limit: int, window: int) -> bool:
    fn = getattr(dashboard_module, '_rate_ok', None)
    if not callable(fn):
        return True
    key = 'walletgen:' + action + ':' + hashlib.sha256(wallet.encode()).hexdigest()[:24]
    return bool(fn(key, limit, window))


def _no_store(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


def _validate_helpers(dashboard_module):
    required = ('encrypt_private_key', 'decrypt_private_key', 'is_valid_solana_private_key')
    return all(callable(getattr(dashboard_module, name, None)) for name in required)


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_trading_wallet_generator_installed', False):
        return
    app._orca_trading_wallet_generator_installed = True

    @app.post(_GENERATE_PATH)
    def _generate_trading_wallet():
        wallet = _auth_wallet(dashboard_module)
        if not wallet:
            return jsonify({'ok': False, 'error': 'Authentication required'}), 401
        if not _csrf_ok(dashboard_module):
            return jsonify({'ok': False, 'error': 'CSRF validation failed'}), 403
        if not _rate_ok(dashboard_module, wallet, 'generate', 5, 3600):
            return jsonify({'ok': False, 'error': 'Too many wallet generations. Try again later.'}), 429

        try:
            sol = Keypair()
            sol_address = str(sol.pubkey())
            sol_private = str(sol)

            evm = Account.create()
            evm_address = str(evm.address)
            evm_private = evm.key.hex()
            if not evm_private.startswith('0x'):
                evm_private = '0x' + evm_private
        except Exception:
            app.logger.exception('trading wallet generation failed')
            return jsonify({'ok': False, 'error': 'Could not generate trading wallet'}), 500

        log_fn = getattr(dashboard_module, '_log_security_event', None)
        if callable(log_fn):
            try:
                log_fn('trading_wallet_generated', wallet,
                       'sol=' + sol_address[:8] + '… evm=' + evm_address[:10] + '…')
            except Exception:
                pass

        # These two secret fields are intentionally allowed only for this exact
        # one-time endpoint by response_privacy_hardening.py. They are never read
        # from the DB and the response is always no-store.
        resp = jsonify({
            'ok': True,
            'solana_address': sol_address,
            'solana_private_key': sol_private,
            'evm_address': evm_address,
            'evm_private_key': evm_private,
            'warning': 'Save both private keys now. OrcAgent will not show generated keys again after confirmation.',
        })
        return _no_store(resp)

    @app.post(_CONFIRM_PATH)
    def _confirm_generated_trading_wallet():
        wallet = _auth_wallet(dashboard_module)
        if not wallet:
            return jsonify({'ok': False, 'error': 'Authentication required'}), 401
        if not _csrf_ok(dashboard_module):
            return jsonify({'ok': False, 'error': 'CSRF validation failed'}), 403
        if not _rate_ok(dashboard_module, wallet, 'confirm', 10, 3600):
            return jsonify({'ok': False, 'error': 'Too many attempts. Try again later.'}), 429
        if not _validate_helpers(dashboard_module):
            app.logger.error('trading wallet generator missing encryption helpers')
            return jsonify({'ok': False, 'error': 'Wallet security backend unavailable'}), 503

        body = request.get_json(silent=True) or {}
        if body.get('backup_confirmed') is not True:
            return jsonify({'ok': False, 'error': 'Confirm that both private keys were saved first'}), 400

        sol_private = str(body.get('solana_private_key') or '').strip()
        evm_private = str(body.get('evm_private_key') or '').strip()
        if not sol_private or not evm_private:
            return jsonify({'ok': False, 'error': 'Both generated private keys are required'}), 400

        valid_sol = getattr(dashboard_module, 'is_valid_solana_private_key')
        if not valid_sol(sol_private):
            return jsonify({'ok': False, 'error': 'Invalid Solana private key'}), 400

        try:
            sol_kp = Keypair.from_base58_string(sol_private)
            sol_address = str(sol_kp.pubkey())
        except Exception:
            return jsonify({'ok': False, 'error': 'Invalid Solana private key'}), 400

        try:
            evm_account = Account.from_key(evm_private)
            evm_address = str(evm_account.address)
        except Exception:
            return jsonify({'ok': False, 'error': 'Invalid EVM private key'}), 400

        # A generated trading wallet should be separate from the login/identity
        # wallet. Accidentally replacing it with the connected Solana wallet would
        # defeat the purpose of keeping a limited-funds trading wallet.
        if sol_address == wallet:
            return jsonify({'ok': False, 'error': 'Trading wallet must be separate from your connected wallet'}), 400

        encrypt = getattr(dashboard_module, 'encrypt_private_key')
        decrypt = getattr(dashboard_module, 'decrypt_private_key')
        try:
            sol_enc = encrypt(sol_private, wallet)
            evm_enc = encrypt(evm_private, wallet)
            if decrypt(sol_enc, wallet) != sol_private or decrypt(evm_enc, wallet) != evm_private:
                raise ValueError('encryption round-trip mismatch')
        except Exception:
            app.logger.exception('generated trading wallet encryption failed')
            return jsonify({'ok': False, 'error': 'Could not securely store trading wallet'}), 500

        db_file = getattr(dashboard_module, 'DB_FILE', None)
        if not db_file:
            return jsonify({'ok': False, 'error': 'Wallet database unavailable'}), 503

        sol_hash = hashlib.sha256(sol_private.encode()).hexdigest()
        try:
            conn = sqlite3.connect(db_file, timeout=10.0)
            try:
                conn.execute('BEGIN IMMEDIATE')
                conn.execute('INSERT OR IGNORE INTO users (wallet_address) VALUES (?)', (wallet,))
                conn.execute(
                    'UPDATE users SET encrypted_private_key=?, key_hash=?, '
                    'bsc_wallet_address=?, encrypted_private_key_bsc=? '
                    'WHERE wallet_address=?',
                    (sol_enc, sol_hash, evm_address, evm_enc, wallet),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        except sqlite3.Error:
            app.logger.exception('generated trading wallet database save failed')
            return jsonify({'ok': False, 'error': 'Could not save trading wallet'}), 503

        state_fn = getattr(dashboard_module, 'get_user_state', None)
        if callable(state_fn):
            try:
                state_fn(wallet)['has_trading_key'] = True
            except Exception:
                pass
        log_fn = getattr(dashboard_module, '_log_security_event', None)
        if callable(log_fn):
            try:
                log_fn('generated_trading_wallet_saved', wallet,
                       'sol=' + sol_address[:8] + '… evm=' + evm_address[:10] + '…')
            except Exception:
                pass

        # Never echo key material after storage.
        return _no_store(jsonify({
            'ok': True,
            'has_trading_key': True,
            'solana_address': sol_address,
            'evm_address': evm_address,
        }))

    @app.after_request
    def _inject_generator_ui(response):
        if request.path != '/settings' or response.mimetype != 'text/html':
            return response
        try:
            html = response.get_data(as_text=True)
            marker = '</head>'
            if marker in html and '/static/trading-wallet-generator.css?v=1' not in html:
                html = html.replace(marker,
                    '<link rel="stylesheet" href="/static/trading-wallet-generator.css?v=1">' + marker, 1)
            marker = '</body>'
            if marker in html and '/static/trading-wallet-generator.js?v=1' not in html:
                html = html.replace(marker,
                    '<script src="/static/trading-wallet-generator.js?v=1"></script>' + marker, 1)
            response.set_data(html)
            response.content_length = len(response.get_data())
        except Exception:
            app.logger.exception('trading wallet generator UI injection failed')
        return response
