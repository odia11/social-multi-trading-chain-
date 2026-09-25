"""A member may use the wallet they signed in with as their trading wallet.

/api/wallet/set-key used to refuse a pasted key whose address matched the
connected wallet ("This is the wallet you connected with -- paste the private
key of a separate, dedicated trading wallet instead"), which blocked members
who simply wanted to trade from their own wallet. It is their key; the modal
they confirm already says it becomes the trading wallet.
"""
import os, sqlite3, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
_DATA = tempfile.mkdtemp()
os.environ.update({'DATA_DIR': _DATA,
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

CSRF = 'tok' * 10
kp = Keypair()
login_wallet = str(kp.pubkey())
login_key = str(kp)                      # base58 secret key of that same wallet
other_key = str(Keypair())

def post_key(key, wallet):
    # The session cookie is Secure and scoped to .orcagent.fun.
    with app.test_client() as c:
        with c.session_transaction(base_url='https://orcagent.fun') as s:
            s['wallet'] = wallet; s['user_id'] = d.get_or_create_user(wallet); s['csrf_token'] = CSRF
        return c.post('/api/wallet/set-key', json={'private_key': key},
                      headers={'X-CSRF-Token': CSRF},
                      base_url='https://orcagent.fun').get_json()

r = post_key(login_key, login_wallet)
check('the login wallet\'s own key is accepted as trading key', r and r.get('ok') is True)
conn = sqlite3.connect(d.DB_FILE)
enc = conn.execute('SELECT encrypted_private_key FROM users WHERE wallet_address=?', (login_wallet,)).fetchone()[0]
conn.close()
check('it is stored encrypted, not in plain text', enc and login_key not in enc)
check('and decrypts back to that exact key', d.decrypt_private_key(enc, login_wallet) == login_key)
check('the trading wallet is the login wallet', d._get_trading_wallet_address(login_wallet) == login_wallet)

# A separate key still works exactly as before.
kp2 = Keypair(); w2 = str(kp2.pubkey())
r = post_key(other_key, w2)
check('a separate trading key is still accepted', r and r.get('ok') is True)
# Garbage is still refused.
r = post_key('not-a-key', w2)
check('an invalid key is still refused', r and r.get('ok') is False)
check('the refusal message is gone from the code',
      'This is the wallet you connected with' not in open(os.path.join(os.path.dirname(__file__), '..', 'dashboard.py')).read())
raise SystemExit(0 if all(checks) else 1)
