"""Optional app-screen lock: isolated real route logic, no trading workers."""
import ast
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from flask import Flask, jsonify, request, session

SOURCE = (Path(__file__).resolve().parents[1] / 'dashboard.py').read_text()
TREE = ast.parse(SOURCE)


def load_function(name, ns):
    n = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)
    n.decorator_list = []
    exec(compile(ast.Module(body=[n], type_ignores=[]), 'dashboard.py', 'exec'), ns)
    return ns[name]


class AppLockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / 'app-lock.db')
        with sqlite3.connect(self.db) as con:
            con.executescript('''
                CREATE TABLE app_lock_preferences (
                    wallet_address TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE webauthn_credentials (
                    id INTEGER PRIMARY KEY, user_id INTEGER, credential_id TEXT UNIQUE,
                    public_key TEXT, sign_count INTEGER DEFAULT 0);
            ''')
            con.execute("INSERT INTO webauthn_credentials VALUES (1,1,'own','pk',0)")
            con.execute("INSERT INTO webauthn_credentials VALUES (2,2,'other','pk',0)")
        self.app=Flask(__name__)
        self.app.secret_key='test-app-lock'
        wa=SimpleNamespace(
            base64url_to_bytes=lambda x: x.encode(),
            verify_authentication_response=lambda **kw: self.verify(**kw))
        self.ns=dict(request=request, session=session, jsonify=jsonify, sqlite3=sqlite3,
                     DB_FILE=self.db, _WEBAUTHN_OK=True, WEBAUTHN_RP_ID='orcagent.fun',
                     _authenticated_wallet=lambda: session.get('wallet',''),
                     _webauthn=wa,
                     _webauthn_pop_challenge=lambda k: b'challenge',
                     _webauthn_expected_origins=lambda: ['https://orcagent.fun'],
                     _log_security_event=lambda *args: None)
        self.pref=load_function('api_app_lock_preference',self.ns)
        self.unlock=load_function('api_app_lock_unlock',self.ns)
    def verify(self,**kw):
        self.assertTrue(kw['require_user_verification'])
        self.assertEqual(kw['expected_rp_id'],'orcagent.fun')
        self.assertEqual(kw['expected_challenge'],b'challenge')
        return SimpleNamespace(new_sign_count=1)
    def invoke(self,fn,method='GET',data=None,user=1,wallet='wallet-a'):
        with self.app.test_request_context('/api/auth/app-lock', method=method, json=data):
            if user: session.update(user_id=user,wallet=wallet)
            result=fn()
            return result if isinstance(result,tuple) else (result,200)
    def test_opt_in_default_and_per_wallet(self):
        a,status=self.invoke(self.pref)
        self.assertEqual(status,200)
        self.assertFalse(a.json['enabled'])
        self.assertTrue(a.json['has_passkey'])
        a,status=self.invoke(self.pref,'POST',{'enabled':True})
        self.assertEqual(status,200)
        self.assertTrue(a.json['enabled'])
        b,_=self.invoke(self.pref,user=2,wallet='wallet-b')
        self.assertFalse(b.json['enabled'])
        a,_=self.invoke(self.pref,'POST',{'enabled':False})
        self.assertFalse(a.json['enabled'])
    def test_cannot_enable_without_passkey_or_auth(self):
        a,status=self.invoke(self.pref,'POST',{'enabled':True},user=3,wallet='wallet-c')
        self.assertEqual(status,409)
        a,status=self.invoke(self.pref,'POST',{'enabled':1})
        self.assertEqual(status,400)
        a,status=self.invoke(self.pref,user=0)
        self.assertEqual(status,401)
    def test_only_same_account_passkey_can_unlock(self):
        a,status=self.invoke(self.unlock,'POST',{'id':'other'})
        self.assertEqual(status,403)
        a,status=self.invoke(self.unlock,'POST',{'id':'own'})
        self.assertEqual(status,200)
        self.assertEqual(a.json['wallet'],'wallet-a')
        with sqlite3.connect(self.db) as con:
            self.assertEqual(con.execute("SELECT sign_count FROM webauthn_credentials WHERE id=1").fetchone()[0],1)
            self.assertEqual(con.execute("SELECT sign_count FROM webauthn_credentials WHERE id=2").fetchone()[0],0)
    def test_no_webauthn_never_enables(self):
        self.ns['_WEBAUTHN_OK']=False
        a,status=self.invoke(self.pref,'POST',{'enabled':True})
        self.assertEqual(status,409)


if __name__=='__main__':
    unittest.main()
