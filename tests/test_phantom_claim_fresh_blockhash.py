"""A freshly prepared creator-fee claim opens Phantom, even if the RPC lags.

A claim was prepared, and one second later "Open Phantom" was refused with
409 "Claim approval expired": the blockhash check asked an RPC node that had
not yet seen the brand-new blockhash and answered "not valid". A blockhash
lives ~60-90s, so a transaction prepared under 45s ago cannot have expired;
older ones are still checked, and a really expired claim is still refused.
"""
import base64, os, sqlite3, time
from unittest.mock import patch
from cryptography.fernet import Fernet
from nacl.public import PrivateKey
from solders.hash import Hash
from solders.instruction import Instruction, AccountMeta
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction
from test_phantom_launch_mobile import setup, prepared_row, lookup
import phantom_launch_mobile as mobile
import token_launch

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

with patch.dict(os.environ, {'ENCRYPTION_KEY': Fernet.generate_key().decode()}):
    with patch.dict(os.environ, {'ENCRYPTION_KEY': ''}):
        tmp, app, d = setup()
    d.csrf_exempt = lambda fn: fn
    asked = []
    # The lagging node: every blockhash it is asked about is "not valid".
    def lagging_node(raw, **kw):
        asked.append(raw); return False
    mobile.install(d, lambda ident, wallet: lookup(d, ident, wallet),
                   lambda *a: False, lambda *a: True, lambda *a: True, lagging_node)
    owner = Keypair(); mint = Keypair()
    launch, _ = prepared_row(d, owner, mint, 'e')
    msg = Message.new_with_blockhash([Instruction(Pubkey.from_string(token_launch.PUMP_PROGRAM),
        b'claim-example', [AccountMeta(owner.pubkey(), True, True)])], owner.pubkey(), Hash.default())
    tx_b64 = base64.b64encode(bytes(Transaction.new_unsigned(msg))).decode()
    def add_claim(cid, age):
        with sqlite3.connect(d.DB_FILE) as db:
            db.execute('''INSERT INTO token_reward_claims
                (id,launch_id,wallet,mint,quote_asset,reward_mode,accrued_raw,accrued_scope,
                 transaction_b64,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (cid, launch, str(owner.pubkey()), str(mint.pubkey()), 'USDC', 'creator',
                 '772156', 'creator_wallet_all_tokens', tx_b64, int(time.time()) - age))
    with sqlite3.connect(d.DB_FILE) as db:
        db.execute("UPDATE token_launches SET status='live' WHERE id=?", (launch,))
    phantom = PrivateKey.generate(); pk = mobile.b58enc(bytes(phantom.public_key))
    mobile.remember_authenticated_session(d.DB_FILE, os.environ['ENCRYPTION_KEY'], str(owner.pubkey()),
        {'wallet_address': str(owner.pubkey()), 'sk': bytes(phantom), 'phantom_pk': pk, 'session': 'mock-session'})
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['wallet'] = str(owner.pubkey()); sess['csrf_token'] = 'test-csrf'
    h = {'X-CSRF-Token': 'test-csrf'}
    path = '/api/token-launch/' + launch + '/claim/phantom/start'

    add_claim('a' * 32, 1)
    r = client.post(path, json={'claim_id': 'a' * 32}, headers=h)
    check('a claim prepared a second ago opens Phantom, even when the RPC node lags',
          r.status_code == 200 and r.get_json().get('url'))
    check('...without asking the lagging node at all', asked == [])

    add_claim('b' * 32, 600)
    r = client.post(path, json={'claim_id': 'b' * 32}, headers=h)
    check('a claim prepared 10 minutes ago is still checked, and refused when expired',
          r.status_code == 409 and 'expired' in r.get_json()['msg'] and len(asked) == 1)

    src = open(os.path.join(os.path.dirname(__file__), '..', 'phantom_launch_mobile.py')).read()
    check('the same grace applies to re-delivery and to the Phantom callback',
          "still_valid(claim['transaction_b64'],claim['created_at'],claim_read=True)" in src
          and "still_valid(original_b64,(claim_for(flow) or {'created_at':0})['created_at'],claim_read=True)" in src)
raise SystemExit(0 if all(checks) else 1)
