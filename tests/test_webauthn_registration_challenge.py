"""Registration options survive iOS passkey sheets and parallel cookie writes."""
import ast
import base64
import hashlib
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

SOURCE=(Path(__file__).resolve().parents[1]/'dashboard.py').read_text()
TREE=ast.parse(SOURCE)
def load(name, ns):
    node=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name==name)
    node.decorator_list=[]
    exec(compile(ast.Module(body=[node],type_ignores=[]),'dashboard.py','exec'),ns)
    return ns[name]

def enc(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')
def dec(raw):
    return base64.urlsafe_b64decode(raw+'='*((-len(raw))%4))

class Challenges(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db=str(Path(tmp.name)/'registration.db')
        with sqlite3.connect(self.db) as c:
            c.executescript('''CREATE TABLE webauthn_registration_challenges(
                challenge_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                wallet_address TEXT NOT NULL,created_at REAL NOT NULL);
                CREATE INDEX idx_web_reg_chal_created ON webauthn_registration_challenges(created_at);''')
        self.ns={'DB_FILE':self.db,'sqlite3':sqlite3,'time':time,'json':json,
                 '_WEBAUTHN_REGISTRATION_TTL_S':600,
                 '_webauthn':SimpleNamespace(base64url_to_bytes=dec)}
        self.store=load('_store_webauthn_registration_challenge',self.ns)
        self.consume=load('_consume_webauthn_registration_challenge',self.ns)
    def credential(self,challenge,kind='webauthn.create'):
        content=json.dumps({'type':kind,'challenge':enc(challenge),
                            'origin':'https://orcagent.fun'}).encode()
        return {'response':{'clientDataJSON':enc(content)}}
    def test_first_time_apple_sheet_takes_three_minutes(self):
        challenge=b'challenge-for-first-time-apple-passwords'
        self.store(challenge,1,'wallet-a')
        with sqlite3.connect(self.db) as c:
            c.execute('UPDATE webauthn_registration_challenges SET created_at=?',
                      (time.time()-180,))
        self.assertEqual(self.consume(self.credential(challenge),1,'wallet-a'),challenge)
        self.assertIsNone(self.consume(self.credential(challenge),1,'wallet-a'))
    def test_concurrent_registration_options_do_not_invalidate_original(self):
        a=b'first-passkey-registration-challenge'
        b=b'newer-prefetch-cannot-kill-first'
        self.store(a,1,'wallet-a')
        self.store(b,1,'wallet-a')
        self.assertEqual(self.consume(self.credential(a),1,'wallet-a'),a)
        self.assertEqual(self.consume(self.credential(b),1,'wallet-a'),b)
    def test_bound_to_account_and_wallet(self):
        ch=b'bound-to-this-wallet'
        self.store(ch,1,'wallet-a')
        self.assertIsNone(self.consume(self.credential(ch),2,'wallet-b'))
        self.assertIsNone(self.consume(self.credential(ch),1,'wallet-other'))
        self.assertEqual(self.consume(self.credential(ch),1,'wallet-a'),ch)
    def test_expiration_type_and_malformed_are_rejected(self):
        ch=b'eventually-expired-apple-credential'
        self.store(ch,1,'wallet-a')
        self.assertIsNone(self.consume(self.credential(ch,'webauthn.get'),1,'wallet-a'))
        self.assertIsNone(self.consume({'response':{'clientDataJSON':'not-json'}},1,'wallet-a'))
        with sqlite3.connect(self.db) as c:
            c.execute('UPDATE webauthn_registration_challenges SET created_at=?',
                      (time.time()-601,))
        self.assertIsNone(self.consume(self.credential(ch),1,'wallet-a'))
    def test_server_issues_and_verifies_only_one_time_registration_challenge(self):
        start=SOURCE.index('def webauthn_register_options():')
        end=SOURCE.index('@app.route',start)
        self.assertIn('_store_webauthn_registration_challenge(options.challenge, user_id, wallet)',SOURCE[start:end])
        start=SOURCE.index('def webauthn_register():')
        end=SOURCE.index('@app.route',start)
        block=SOURCE[start:end]
        self.assertIn('_consume_webauthn_registration_challenge(body, user_id, wallet)',block)
        self.assertIn('verify_registration_response(',block)
        self.assertIn('require_user_verification=True',block)

if __name__=='__main__':unittest.main()
