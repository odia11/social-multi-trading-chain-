import datetime
import sqlite3
import tempfile
from types import SimpleNamespace

from flask import Flask, jsonify

from auth_replay_hardening import install


def make_app():
    db = tempfile.mktemp(suffix='.db')
    con = sqlite3.connect(db)
    con.execute('CREATE TABLE auth_nonces (nonce TEXT PRIMARY KEY, created_at TEXT)')
    con.commit(); con.close()
    app = Flask(__name__)
    mod = SimpleNamespace(app=app, DB_FILE=db)
    install(mod)

    @app.post('/api/wallet/set')
    def set_wallet():
        return jsonify(ok=True)
    return app, db


def add_nonce(db, nonce, age_seconds=0):
    created = datetime.datetime.utcnow() - datetime.timedelta(seconds=age_seconds)
    con = sqlite3.connect(db)
    con.execute('INSERT INTO auth_nonces(nonce, created_at) VALUES (?,?)',
                (nonce, created.strftime('%Y-%m-%d %H:%M:%S')))
    con.commit(); con.close()


app, db = make_app()
c = app.test_client()
add_nonce(db, 'fresh')
r1 = c.post('/api/wallet/set', json={'address':'WALLET','nonce':'fresh'})
r2 = c.post('/api/wallet/set', json={'address':'WALLET','nonce':'fresh'})
assert r1.status_code == 200, r1.get_data(as_text=True)
assert r2.status_code == 409, r2.get_data(as_text=True)

add_nonce(db, 'old', age_seconds=601)
r3 = c.post('/api/wallet/set', json={'address':'WALLET','nonce':'old'})
assert r3.status_code == 401, r3.get_data(as_text=True)

# Disconnect uses the historical empty-address call and is not a login replay.
r4 = c.post('/api/wallet/set', json={'address':''})
assert r4.status_code == 200, r4.get_data(as_text=True)
print('wallet nonce replay protection: PASS')
