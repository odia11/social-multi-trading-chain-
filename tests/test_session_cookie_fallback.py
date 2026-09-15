"""Execute recovery against SQLite without starting trading workers."""
import ast
import hashlib
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time
import unittest
from types import SimpleNamespace

SOURCE = (Path(__file__).resolve().parents[1] / 'dashboard.py').read_text()
TREE = ast.parse(SOURCE)

class Response:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}
        self.status_code = 200

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / 'sessions.db')
        with sqlite3.connect(self.db) as conn:
            conn.execute('CREATE TABLE device_sessions (id INTEGER PRIMARY KEY, user_id INTEGER, wallet TEXT, token_hash TEXT UNIQUE, created_at REAL, last_used_at REAL, expires_at REAL, revoked INTEGER DEFAULT 0)')
        class Session(dict):
            pass
        self.ns = dict(sqlite3=sqlite3, hashlib=hashlib, secrets=secrets, time=time,
                       DB_FILE=self.db, DEVICE_TOKEN_DAYS=3650, DEVICE_COOKIE_NAME='orca_device',
                       request=SimpleNamespace(json={}, cookies={}), session=Session(),
                       jsonify=Response, get_or_create_user=lambda w: 1,
                       _get_csrf_token=lambda: 'csrf', _set_device_cookie=lambda r,t:r)
        for name in ('_hash_device_token', '_issue_device_token', '_redeem_device_token', '_revoke_device_tokens', 'api_session_resume'):
            node = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)
            exec(ast.get_source_segment(SOURCE, node), self.ns)

    def token(self, wallet='wallet-a'):
        return self.ns['_issue_device_token'](1, wallet)

    def resume(self, explicit='', cookie=''):
        self.ns['request'].json = {'token': explicit}
        self.ns['request'].cookies = {'orca_device': cookie}
        return self.ns['api_session_resume']()

    def test_stale_local_token_falls_back_to_cookie(self):
        token = self.token()
        response = self.resume('stale', token)
        self.assertEqual(response.payload['wallet'], 'wallet-a')
        self.assertEqual(response.payload['token'], token)

    def test_cookie_only_recovery(self):
        self.assertTrue(self.resume(cookie=self.token()).payload['ok'])

    def test_valid_explicit_token_keeps_precedence(self):
        explicit = self.token('wallet-b')
        self.assertEqual(self.resume(explicit, self.token()).payload['wallet'], 'wallet-b')

    def test_revoked_tokens_do_not_restore(self):
        token = self.token()
        self.ns['_revoke_device_tokens']('wallet-a')
        self.assertEqual(self.resume(token, token)[1], 401)

    def test_unknown_credentials_are_rejected(self):
        self.assertEqual(self.resume('unknown', 'unknown-cookie')[1], 401)

    def test_storage_failure_is_retryable(self):
        token = self.token()
        self.ns['DB_FILE'] = self.tmp.name  # A directory cannot be opened as SQLite.
        response = self.resume(token)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers['Retry-After'], '3')
        self.ns['DB_FILE'] = self.db
        self.assertTrue(self.resume(token).payload['ok'])

if __name__ == '__main__':
    unittest.main()
