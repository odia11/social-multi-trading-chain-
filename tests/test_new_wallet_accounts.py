"""Runtime tests using the monolith's actual auth/encryption/user helpers.

Extracting functions avoids booting scanners/RPC threads or production secrets.
"""
import ast
import base64
import binascii
from concurrent.futures import ThreadPoolExecutor
import datetime
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from types import SimpleNamespace

import bcrypt
from cryptography.fernet import Fernet, InvalidToken
from flask import Flask, g, has_request_context, jsonify, request, session
import pytest
from solders.keypair import Keypair

import new_wallet_accounts as accounts
from response_privacy_hardening import install as install_privacy

ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / 'dashboard.py').read_text())


def extract(name, namespace):
    node = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)
    node = ast.parse(ast.unparse(node)).body[0]
    node.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(ROOT / 'dashboard.py'), 'exec'), namespace)
    return namespace[name]


@pytest.fixture
def setup(tmp_path):
    app = Flask(__name__)
    app.secret_key = secrets.token_hex(32)
    app.config['TESTING'] = True
    db = str(tmp_path / 'accounts.db')
    with sqlite3.connect(db) as conn:
        conn.executescript('''CREATE TABLE users (
          id INTEGER PRIMARY KEY, wallet_address TEXT UNIQUE, username TEXT,
          password_hash TEXT, encrypted_private_key TEXT, key_hash TEXT,
          pref_solana_base_currency TEXT, referral_code TEXT, referred_by TEXT);
          CREATE TABLE device_sessions(user_id INTEGER, wallet TEXT, token_hash TEXT,
          created_at REAL, last_used_at REAL, expires_at REAL);
          CREATE TABLE auth_nonces(nonce TEXT PRIMARY KEY, created_at TEXT);
        ''')
    states = {}
    namespace = dict(app=app, DB_FILE=db, sqlite3=sqlite3, session=session, secrets=secrets,
                     hashlib=hashlib, hmac=hmac, base64=base64, binascii=binascii,
                     Fernet=Fernet, InvalidToken=InvalidToken, has_request_context=has_request_context,
                     _REFERRAL_CODE_ALPHABET='ABCDEFGHJKLMNPQRSTUVWXYZ23456789',
                     _enc_key_str=Fernet.generate_key().decode(), _enc_key_fingerprint='test',
                     jsonify=jsonify, request=request, g=g, time=time,
                     DEVICE_COOKIE_NAME='orca_device', DEVICE_TOKEN_DAYS=90)
    namespace['_fernet'] = Fernet(namespace['_enc_key_str'].encode())
    for name in ('_authenticated_wallet', '_get_csrf_token', '_validate_csrf', '_wallet_fernet',
                 'encrypt_private_key', 'decrypt_private_key', '_generate_referral_code',
                 'get_or_create_user', '_hash_device_token', '_issue_device_token', '_set_device_cookie'):
        extract(name, namespace)
    namespace['get_user_state'] = lambda w: states.setdefault(w, {})
    d = SimpleNamespace(**namespace)
    # Register the production scanner before module hooks, just as app_entry does.
    namespace.update(IS_PRODUCTION=False, json=json, _KEY_REVEAL_PATHS=frozenset(),
                     _KEY_LEAK_RE=__import__('re').compile(r'[1-9A-HJ-NP-Za-km-z]{87,88}'),
                     _FORBIDDEN_RESPONSE_KEYS=frozenset({'private_key', 'password_hash'}),
                     _scan_obj_for_key_leak=lambda obj: ('private_key', obj['private_key'][:8]) if isinstance(obj, dict) and 'private_key' in obj else None)
    app.after_request(extract('_security_headers', namespace))
    accounts.install(d)
    install_privacy(d)
    namespace.update(_bcrypt=bcrypt, _LOGIN_DUMMY_BCRYPT_HASH=bcrypt.hashpw(b'dummy', bcrypt.gensalt(rounds=12)),
                     _record_ip_failure=lambda ip: None, add_user_log=lambda *args: None,
                     _is_owner=lambda wallet: False)
    app.add_url_rule('/api/login_password', view_func=extract('login_password', namespace), methods=['POST'])

    @app.get('/api/csrf-token')
    def csrf():
        return {'token': d._get_csrf_token()}

    @app.get('/probe')
    def probe():
        return '<html><head></head><body></body></html>'

    return app, d, states


def client_with_csrf(app):
    client = app.test_client()
    token = client.get('/api/csrf-token').json['token']
    return client, {'X-CSRF-Token': token}


def start(client, headers):
    result = client.post(accounts.START, json={}, headers=headers)
    assert result.status_code == 200
    return result.json


def confirm(client, headers, wallet, **overrides):
    body = dict(token=wallet['token'], confirmed_backup=True, username='new_user', password='correct horse battery')
    body.update(overrides)
    return client.post(accounts.CONFIRM, json=body, headers=headers)


def test_activation_encryption_session_password_device_and_replay(setup, capsys):
    app, d, states = setup
    c, headers = client_with_csrf(app)
    with c.session_transaction() as s:
        s['wallet'], s['readonly'], s['user_id'] = 'old-view-only', True, 123
    wallet = start(c, headers)
    assert str(Keypair.from_base58_string(wallet['private_key']).pubkey()) == wallet['address']
    with sqlite3.connect(d.DB_FILE) as conn:
        assert conn.execute('SELECT count(*) FROM users').fetchone()[0] == 0
    result = confirm(c, headers, wallet)
    assert result.status_code == 200
    assert result.json['has_trading_key'] is True
    assert 'private_key' not in result.json
    assert 'no-store' in result.headers['Cache-Control']
    assert any('orca_device=' in cookie and 'HttpOnly' in cookie for cookie in result.headers.getlist('Set-Cookie'))
    with c.session_transaction() as s:
        assert s['wallet'] == wallet['address'] and s['user_id'] != 123
        assert 'readonly' not in s and s.permanent
        assert s['csrf_token'] != headers['X-CSRF-Token']
    with sqlite3.connect(d.DB_FILE) as conn:
        encrypted, key_hash, pw_hash, user = conn.execute('SELECT encrypted_private_key,key_hash,password_hash,username FROM users').fetchone()
        assert encrypted.startswith('v2:') and d.decrypt_private_key(encrypted, wallet['address']) == wallet['private_key']
        assert key_hash == hashlib.sha256(wallet['private_key'].encode()).hexdigest()
        assert bcrypt.checkpw(b'correct horse battery', pw_hash.encode()) and pw_hash.startswith('$2b$12$')
        assert user == 'new_user'
        assert conn.execute('SELECT count(*) FROM device_sessions').fetchone()[0] == 1
    assert states[wallet['address']]['has_trading_key']
    fresh = app.test_client()
    login = fresh.post('/api/login_password', json={'username': 'new_user', 'password': 'correct horse battery'})
    assert login.status_code == 200 and login.json['wallet'] == wallet['address'] and login.json['has_trading_key']
    with fresh.session_transaction() as s:
        assert s['wallet'] == wallet['address'] and s['user_id']
    assert wallet['private_key'] not in capsys.readouterr().out
    with c.session_transaction() as s:
        s.clear(); s['csrf_token'] = headers['X-CSRF-Token']
    assert confirm(c, headers, wallet).status_code == 400


def test_guards_expiry_and_ip_limit(setup, monkeypatch):
    app, _, _ = setup
    c, headers = client_with_csrf(app)
    assert c.post(accounts.START, json={}).status_code == 403
    now = time.monotonic()
    monkeypatch.setattr(accounts.time, 'monotonic', lambda: now)
    wallet = start(c, headers)
    other, other_headers = client_with_csrf(app)
    assert confirm(other, other_headers, wallet).status_code == 400
    start(c, headers); start(c, headers)
    assert c.post(accounts.START, json={}, headers={**headers, 'X-Real-IP': 'different'}).status_code == 429
    monkeypatch.setattr(accounts.time, 'monotonic', lambda: now + 601)
    assert confirm(c, headers, wallet).status_code == 400
    monkeypatch.setattr(accounts.time, 'monotonic', lambda: now + 3601)
    start(c, headers)
    with c.session_transaction() as s:
        s['wallet'] = 'full-account'
    assert c.post(accounts.START, json={}, headers=headers).status_code == 409
    assert c.post(accounts.CONFIRM, json={}, headers=headers).status_code == 409


@pytest.mark.parametrize('overrides', [dict(confirmed_backup=False), dict(confirmed_backup='true'),
                         dict(username=''), dict(username='bad name'), dict(username='x'*21),
                         dict(password='short'), dict(password='é'*37)])
def test_invalid_confirmation_consumes_token_and_stores_nothing(setup, overrides):
    app, d, _ = setup
    c, headers = client_with_csrf(app)
    wallet = start(c, headers)
    assert confirm(c, headers, wallet, **overrides).status_code == 400
    assert confirm(c, headers, wallet).status_code == 400
    with sqlite3.connect(d.DB_FILE) as conn:
        assert conn.execute('SELECT count(*) FROM users').fetchone()[0] == 0


def test_unique_username_and_atomic_rollback(setup):
    app, d, _ = setup
    c, headers = client_with_csrf(app)
    with sqlite3.connect(d.DB_FILE) as conn:
        conn.execute("INSERT INTO users(wallet_address, username) VALUES ('existing', 'NEW_USER')")
    wallet = start(c, headers)
    assert confirm(c, headers, wallet).status_code == 409
    with sqlite3.connect(d.DB_FILE) as conn:
        assert not conn.execute('SELECT 1 FROM users WHERE wallet_address=?', (wallet['address'],)).fetchone()
        conn.execute("CREATE TRIGGER fail_save BEFORE UPDATE OF encrypted_private_key ON users BEGIN SELECT RAISE(ABORT,'save rejected'); END")
    wallet = start(c, headers)
    assert confirm(c, headers, wallet, username='available').status_code == 503
    with sqlite3.connect(d.DB_FILE) as conn:
        assert not conn.execute('SELECT 1 FROM users WHERE wallet_address=?', (wallet['address'],)).fetchone()


def test_concurrent_one_time_confirm(setup):
    app, d, _ = setup
    c, headers = client_with_csrf(app)
    wallet = start(c, headers)
    cookie = c.get_cookie('session').value
    def submit():
        client = app.test_client(); client.set_cookie('session', cookie)
        return confirm(client, headers, wallet).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(pool.map(lambda _: submit(), range(2)))
    assert codes == [200, 400]
    with sqlite3.connect(d.DB_FILE) as conn:
        assert conn.execute('SELECT count(*) FROM users').fetchone()[0] == 1


def test_html_assets_and_export_validation(setup):
    app, _, _ = setup
    html = app.test_client().get('/probe').text
    assert '/static/new-wallet.css' in html and '/static/new-wallet.js' in html
    assert html.index('tweetnacl-1.0.3.min.js') < html.index('new-wallet.js')
    kp = Keypair()
    payload = dict(ok=True, address=str(kp.pubkey()), private_key=str(kp), token='t'*43)
    assert accounts.valid_key_export(payload)
    assert not accounts.valid_key_export({**payload, 'extra_secret': 'secret'})
    assert not accounts.valid_key_export({**payload, 'address': str(Keypair().pubkey())})


def test_existing_user_helper_still_commits_without_transaction(setup):
    _, d, _ = setup
    uid = d.get_or_create_user('original-call')
    with sqlite3.connect(d.DB_FILE) as conn:
        assert conn.execute('SELECT id FROM users WHERE wallet_address=?', ('original-call',)).fetchone()[0] == uid


def test_concurrent_username_uniqueness(setup):
    app, d, _ = setup
    c, headers = client_with_csrf(app)
    one, two = start(c, headers), start(c, headers)
    cookie = c.get_cookie('session').value
    def submit(wallet):
        client = app.test_client(); client.set_cookie('session', cookie)
        return confirm(client, headers, wallet).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(pool.map(submit, [one, two]))
    assert codes == [200, 409]
    with sqlite3.connect(d.DB_FILE) as conn:
        assert conn.execute('SELECT count(*) FROM users').fetchone()[0] == 1
