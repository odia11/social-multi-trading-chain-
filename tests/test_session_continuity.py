"""Real Flask cookies + SQLite + Ed25519; production auth functions, no trading workers."""
import ast
import datetime
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest

from flask import Flask, g, jsonify, request, session
import nacl.signing

SOURCE_PATH = Path(__file__).resolve().parents[1] / 'dashboard.py'
SOURCE = SOURCE_PATH.read_text()
TREE = ast.parse(SOURCE)
BASE = 'https://orcagent.fun'

class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / 'sessions.db')
        with sqlite3.connect(self.db) as db:
            db.executescript('''
                CREATE TABLE users (id INTEGER PRIMARY KEY, wallet_address TEXT UNIQUE, encrypted_private_key TEXT);
                CREATE TABLE auth_nonces (nonce TEXT PRIMARY KEY, created_at TEXT);
                CREATE TABLE device_sessions (id INTEGER PRIMARY KEY, user_id INTEGER, wallet TEXT, token_hash TEXT UNIQUE, created_at REAL, last_used_at REAL, expires_at REAL, revoked INTEGER DEFAULT 0);
            ''')
        self.app, self.ns = self.make_app()
        self.client = self.app.test_client()
        self.signer = nacl.signing.SigningKey.generate()
        self.wallet = self.ns['_b58enc'](bytes(self.signer.verify_key))

    def make_app(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SESSION_COOKIE_NAME='orca_s',
                          SESSION_COOKIE_DOMAIN='.orcagent.fun', SESSION_COOKIE_PATH='/',
                          SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True,
                          SESSION_COOKIE_SAMESITE='Lax')
        def user(wallet, ref=None):
            with sqlite3.connect(self.db) as db:
                db.execute('INSERT OR IGNORE INTO users(wallet_address) VALUES (?)', (wallet,))
                return db.execute('SELECT id FROM users WHERE wallet_address=?', (wallet,)).fetchone()[0]
        alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
        ns = dict(app=app, g=g, session=session, request=request, jsonify=jsonify,
                  __file__=str(SOURCE_PATH), os=os, sqlite3=sqlite3, hashlib=hashlib,
                  hmac=hmac, secrets=secrets, time=time, datetime=datetime,
                  DB_FILE=self.db, DEVICE_TOKEN_DAYS=3650, DEVICE_COOKIE_NAME='orca_device',
                  get_or_create_user=user, _B58_ALPHA=alphabet,
                  _B58_MAP={c:i for i,c in enumerate(alphabet)},
                  _SOLANA_ADDR_RE=re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$'),
                  _NACL_OK=True, _nacl_signing=nacl.signing, _phantom_pair_pending={},
                  threading=SimpleNamespace(Thread=lambda **kw:SimpleNamespace(start=lambda:None)),
                  fetch_user_balances=lambda *a:None, add_user_log=lambda *a:None,
                  _check_wallet_multi_ip=lambda *a:None, get_user_state=lambda *a:{},
                  _is_owner=lambda w:False, API_SHARED_SECRET='',
                  _CSRF_EXEMPT_PATHS={'/api/wallet/set'}, _log_security_event=lambda *a:None)
        names = ('_load_secret_key', '_b58enc', '_b58dec', 'is_valid_solana_address',
                 '_get_csrf_token', '_validate_csrf', '_csrf_check', '_authenticated_wallet',
                 '_current_wallet', '_hash_device_token', '_issue_device_token',
                 '_redeem_device_token', '_revoke_device_tokens', '_set_device_cookie',
                 '_clear_device_cookie', '_restore_remembered_request', '_refresh_session',
                 '_persist_remembered_session', 'set_wallet', 'logout', 'api_session_remember',
                 'api_session_resume', 'api_session')
        for name in names:
            node = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)
            exec(ast.get_source_segment(SOURCE, node), ns)
        app.secret_key = ns['_load_secret_key'](self.tmp.name)
        app.before_request(ns['_refresh_session'])
        app.before_request(ns['_csrf_check'])
        app.after_request(ns['_persist_remembered_session'])
        for rule, name in [('/api/wallet/set','set_wallet'),('/api/logout','logout'),
                           ('/api/session/remember','api_session_remember'),('/api/session/resume','api_session_resume')]:
            if name in ('logout','api_session_resume'):
                ns[name]._csrf_exempt=True
            app.add_url_rule(rule, name, ns[name], methods=['POST'])
        app.add_url_rule('/api/session', 'api_session', ns['api_session'])
        def page():
            wallet=ns['_authenticated_wallet']()
            if not wallet:
                return 'Login required', 401
            return '<html>Signed in</html>'
        for i,route in enumerate(('/', '/wallet', '/live-market')):
            app.add_url_rule(route, 'page'+str(i), page)
        app.add_url_rule('/api/protected', 'protected', lambda:jsonify(ok=True), methods=['POST'])
        return app,ns

    def login(self):
        nonce=secrets.token_hex(16)
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT INTO auth_nonces VALUES (?,?)', (nonce, datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')))
        message='OrcAgent verification\n\nCode: '+nonce
        signature=self.ns['_b58enc'](self.signer.sign(message.encode()).signature)
        r=self.client.post('/api/wallet/set',base_url=BASE,json=dict(address=self.wallet,nonce=nonce,signature=signature))
        self.assertEqual(r.status_code,200)
        self.assertTrue(r.json['ok'])
        return r

    def cookie(self,name='orca_device'):
        return self.client.get_cookie(name,domain='orcagent.fun')

    def lose_session(self):
        self.client.delete_cookie('orca_s',domain='orcagent.fun')

    def test_signed_login_and_reopen_all_routes(self):
        r=self.login()
        self.assertEqual(self.cookie().value,r.json['device_token'])
        for route in ('/','/wallet','/live-market'):
            self.assertEqual(self.client.get(route,base_url=BASE).status_code,200)
        self.assertTrue(self.cookie().secure)
        self.assertTrue(self.cookie().http_only)
        self.assertEqual(self.cookie().same_site,'Lax')

    def test_cookie_restores_before_protected_page(self):
        self.login(); token=self.cookie().value; self.lose_session()
        self.assertEqual(self.client.get('/wallet',base_url=BASE).status_code,200)
        self.assertEqual(self.cookie().value,token)
        self.assertIsNotNone(self.cookie('orca_s'))

    def test_process_restart_uses_persisted_key_and_database(self):
        self.login(); old_key=self.app.secret_key
        app,ns=self.make_app()
        self.assertEqual(app.secret_key,old_key)
        self.client.application=app
        self.assertEqual(self.client.get('/wallet',base_url=BASE).status_code,200)

    def test_device_cookie_even_recovers_changed_signing_key(self):
        self.login(); self.app.secret_key=secrets.token_bytes(32)
        self.assertEqual(self.client.get('/wallet',base_url=BASE).status_code,200)

    def test_www_and_bare_domain_share_session(self):
        self.login(); self.lose_session()
        self.assertEqual(self.client.get('/wallet',base_url='https://www.orcagent.fun').status_code,200)
        self.assertEqual(self.client.get('/',base_url=BASE).status_code,200)

    def test_legacy_session_backfills_cookie_without_js_or_csrf_post(self):
        uid=self.ns['get_or_create_user'](self.wallet)
        with self.client.session_transaction(base_url=BASE) as s:
            s['wallet']=self.wallet; s['user_id']=uid; s.permanent=True
        self.assertIsNone(self.cookie())
        self.assertEqual(self.client.get('/',base_url=BASE).status_code,200)
        self.assertIsNotNone(self.cookie())

    def test_logout_after_session_loss_revokes_cookie(self):
        self.login(); token=self.cookie().value; self.lose_session()
        self.assertEqual(self.client.post('/api/logout',base_url=BASE).status_code,200)
        self.assertIsNone(self.cookie())
        self.client.set_cookie('orca_device',token,domain='orcagent.fun')
        self.assertEqual(self.client.get('/wallet',base_url=BASE).status_code,401)

    def test_readonly_is_never_upgraded_or_remembered(self):
        with self.client.session_transaction(base_url=BASE) as s:
            s['wallet']=self.wallet; s['readonly']=True
        self.assertEqual(self.client.get('/wallet',base_url=BASE).status_code,401)
        self.assertIsNone(self.cookie())

    def test_unknown_cookie_never_grants_access(self):
        self.client.set_cookie('orca_device','unknown',domain='orcagent.fun')
        self.assertEqual(self.client.get('/wallet',base_url=BASE).status_code,401)

    def test_recovery_keeps_csrf_enforcement(self):
        self.login(); self.lose_session()
        self.assertEqual(self.client.post('/api/protected',base_url=BASE).status_code,403)
        r=self.client.get('/api/session',base_url=BASE)
        self.assertEqual(self.client.post('/api/protected',base_url=BASE,headers={'X-CSRF-Token':r.json['csrf_token']}).status_code,200)
        self.assertEqual(self.client.post('/api/logout',base_url=BASE,headers={'Origin':'https://attacker.example'}).status_code,403)

    def test_remember_reuses_existing_token(self):
        self.login(); token=self.cookie().value
        me=self.client.get('/api/session',base_url=BASE)
        r=self.client.post('/api/session/remember',base_url=BASE,headers={'X-CSRF-Token':me.json['csrf_token']})
        self.assertEqual(r.json['token'],token)

    def test_storage_outage_preserves_cookie_and_recovers_later(self):
        self.login(); token=self.cookie().value; self.lose_session()
        self.ns['DB_FILE']=self.tmp.name
        self.assertEqual(self.client.get('/wallet',base_url=BASE).status_code,503)
        self.assertEqual(self.cookie().value,token)
        self.ns['DB_FILE']=self.db
        self.assertEqual(self.client.get('/wallet',base_url=BASE).status_code,200)

if __name__=='__main__':
    unittest.main()
