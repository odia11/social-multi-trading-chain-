"""Regression tests for generated Solana + EVM trading-wallet onboarding."""
import os
import sqlite3
import tempfile
from types import SimpleNamespace

from flask import Flask
from solders.keypair import Keypair
from eth_account import Account
from cryptography.fernet import Fernet

from trading_wallet_generator import install as install_generator
from response_privacy_hardening import install as install_privacy


fd, db_path = tempfile.mkstemp(suffix='.db')
os.close(fd)
conn = sqlite3.connect(db_path)
conn.executescript('''
CREATE TABLE users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  wallet_address TEXT UNIQUE,
  encrypted_private_key TEXT DEFAULT '',
  key_hash TEXT DEFAULT '',
  bsc_wallet_address TEXT DEFAULT '',
  encrypted_private_key_bsc TEXT DEFAULT ''
);
INSERT INTO users(wallet_address) VALUES ('IDENTITY_WALLET');
''')
conn.commit(); conn.close()

app = Flask(__name__)
state = {}
logs = []
fernet = Fernet(Fernet.generate_key())


def enc(raw, wallet):
    return fernet.encrypt((wallet + '\0' + raw).encode()).decode()


def dec(blob, wallet):
    value = fernet.decrypt(blob.encode()).decode()
    prefix = wallet + '\0'
    if not value.startswith(prefix):
        raise ValueError('wrong wallet')
    return value[len(prefix):]


def valid_sol(raw):
    try:
        Keypair.from_base58_string(raw)
        return True
    except Exception:
        return False

mod = SimpleNamespace(
    app=app,
    DB_FILE=db_path,
    _authenticated_wallet=lambda: 'IDENTITY_WALLET',
    _validate_csrf=lambda token: token == 'csrf-ok',
    _rate_ok=lambda *args: True,
    encrypt_private_key=enc,
    decrypt_private_key=dec,
    is_valid_solana_private_key=valid_sol,
    get_user_state=lambda wallet: state.setdefault(wallet, {}),
    _log_security_event=lambda *args: logs.append(args),
)

install_generator(mod)
install_privacy(mod)

@app.get('/api/test-secret')
def secret_probe():
    return {'ok': True, 'private_key': 'must-not-leak'}

client = app.test_client()
headers = {'X-CSRF-Token': 'csrf-ok'}

checks = []
def check(name, ok):
    checks.append(bool(ok)); print(('PASS ' if ok else 'FAIL ') + name)

r = client.post('/api/wallet/generate-trading-wallet')
check('generation requires CSRF proof', r.status_code == 403)

r = client.post('/api/wallet/generate-trading-wallet', headers=headers)
payload = r.get_json()
check('generation succeeds for authenticated user', r.status_code == 200 and payload.get('ok') is True)
check('Solana public + private key are returned once', bool(payload.get('solana_address')) and bool(payload.get('solana_private_key')))
check('EVM public + private key are returned once', bool(payload.get('evm_address')) and bool(payload.get('evm_private_key')))
check('one-time export is explicitly no-store', 'no-store' in (r.headers.get('Cache-Control') or ''))
check('Solana key derives the advertised address', str(Keypair.from_base58_string(payload['solana_private_key']).pubkey()) == payload['solana_address'])
check('EVM key derives the advertised address', Account.from_key(payload['evm_private_key']).address.lower() == payload['evm_address'].lower())

conn = sqlite3.connect(db_path)
row = conn.execute('SELECT encrypted_private_key, encrypted_private_key_bsc FROM users WHERE wallet_address=?', ('IDENTITY_WALLET',)).fetchone()
conn.close()
check('generation alone stores no private key', row == ('', ''))

body = {
    'solana_private_key': payload['solana_private_key'],
    'evm_private_key': payload['evm_private_key'],
    'backup_confirmed': False,
}
r2 = client.post('/api/wallet/generated/confirm', headers=headers, json=body)
check('storage is blocked until user confirms backup', r2.status_code == 400)

body['backup_confirmed'] = True
r3 = client.post('/api/wallet/generated/confirm', headers=headers, json=body)
p3 = r3.get_json()
check('confirmed generated wallet is saved', r3.status_code == 200 and p3.get('ok') is True)
check('save response never echoes private keys', 'solana_private_key' not in p3 and 'evm_private_key' not in p3)

conn = sqlite3.connect(db_path)
row = conn.execute('SELECT encrypted_private_key, key_hash, bsc_wallet_address, encrypted_private_key_bsc FROM users WHERE wallet_address=?', ('IDENTITY_WALLET',)).fetchone()
conn.close()
check('Solana key is persisted only as ciphertext', bool(row[0]) and payload['solana_private_key'] not in row[0])
check('EVM wallet address is persisted for all EVM chains', row[2].lower() == payload['evm_address'].lower())
check('EVM key is persisted only as ciphertext', bool(row[3]) and payload['evm_private_key'] not in row[3])
check('stored Solana ciphertext decrypts only for identity wallet', dec(row[0], 'IDENTITY_WALLET') == payload['solana_private_key'])
check('stored EVM ciphertext decrypts only for identity wallet', dec(row[3], 'IDENTITY_WALLET') == payload['evm_private_key'])
check('runtime marks trading key ready', state.get('IDENTITY_WALLET', {}).get('has_trading_key') is True)
check('security events never receive plaintext key material', all(payload['solana_private_key'] not in str(x) and payload['evm_private_key'] not in str(x) for x in logs))

# The new-user generator must never silently rotate an existing funded wallet.
r_existing = client.post('/api/wallet/generate-trading-wallet', headers=headers)
check('existing trading wallet cannot be overwritten by generator', r_existing.status_code == 409)

r4 = client.get('/api/test-secret')
check('privacy guard still strips private keys everywhere else', 'private_key' not in r4.get_json())

os.unlink(db_path)
raise SystemExit(0 if all(checks) else 1)
