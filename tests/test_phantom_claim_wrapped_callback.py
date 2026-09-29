"""A creator-fee claim Phantom signed WITH its standard wrapper is accepted.

When Phantom signs a claim it may add two compute-budget instructions and two
Lighthouse (L2TEx) guard instructions. The on-chain check already accepted
exactly that wrapper, but the Phantom callback demanded a byte-identical
message, so every such approval failed with "Phantom signature did not match
this exact token launch" (seen in production). Now the callback and the
re-delivery accept that wrapper -- the Pump claim itself must stay identical
and the added priority fee must fit the claim's SOL budget -- and still reject
anything else.
"""
import base64, os, sqlite3, sys, time
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from unittest.mock import patch
from cryptography.fernet import Fernet
from nacl.public import PrivateKey
from solders.hash import Hash
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from test_claim_phantom_wrapper import build_claim  # noqa: E402
from test_creator_rewards_preflight import fixture  # noqa: E402
from test_phantom_launch_mobile import setup, prepared_row, lookup, make_reply  # noqa: E402
import phantom_launch_mobile as mobile  # noqa: E402
import token_launch  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

# The real check from token_launch (closure exposed as a test hook).
_tmp, tl_app, *_ = fixture()
wrapper_ok = tl_app._orca_phantom_claim_wrapper_ok

owner = Keypair(); wallet = str(owner.pubkey())
original, wrapped, _ata = build_claim(owner)
check('the standard Phantom wrapper is accepted', wrapper_ok(wrapped.message, original.message, wallet))
_, tampered, _ = build_claim(owner, bad_core=True)
check('a changed Pump claim is still rejected', not wrapper_ok(tampered.message, original.message, wallet))
# Same wrapper but a priority fee far above the claim's SOL budget.
compute = Pubkey.from_string(token_launch.COMPUTE_BUDGET_PROGRAM)
ixs = list(wrapped.message.instructions)
msg = wrapped.message
keys = msg.account_keys
hdr = msg.header
def writable(a):
    n = hdr.num_required_signatures
    return a < n - hdr.num_readonly_signed_accounts if a < n else a < len(keys) - hdr.num_readonly_unsigned_accounts
def ins(i):
    ix = msg.instructions[i]
    from solders.instruction import AccountMeta
    return Instruction(keys[ix.program_id_index], bytes(ix.data),
                       [AccountMeta(keys[a], msg.is_signer(a), writable(a)) for a in ix.accounts])
greedy = [Instruction(compute, b'\x02' + (1_400_000).to_bytes(4, 'little'), []),
          Instruction(compute, b'\x03' + (100_000_000).to_bytes(8, 'little'), [])] + [ins(i) for i in range(2, len(msg.instructions))]
greedy_msg = Message.new_with_blockhash(greedy, owner.pubkey(), Hash.default())
check('a wrapper with an excessive priority fee is rejected before relaying',
      not wrapper_ok(greedy_msg, original.message, wallet))

# ── end to end through the Phantom callback ──
with patch.dict(os.environ, {'ENCRYPTION_KEY': Fernet.generate_key().decode()}):
    with patch.dict(os.environ, {'ENCRYPTION_KEY': ''}):
        tmp, app, d = setup()
    d.csrf_exempt = lambda fn: fn
    mobile.install(d, lambda ident, w: lookup(d, ident, w), lambda *a: False, lambda *a: True, lambda *a: True,
                   lambda raw, **kw: True, wrapper_ok)
    mint = Keypair()
    launch, _ = prepared_row(d, owner, mint, 'e')
    claim_id = 'f' * 32
    with sqlite3.connect(d.DB_FILE) as db:
        db.execute("UPDATE token_launches SET status='live' WHERE id=?", (launch,))
        db.execute('''INSERT INTO token_reward_claims (id,launch_id,wallet,mint,quote_asset,reward_mode,accrued_raw,
            accrued_scope,transaction_b64,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (claim_id, launch, wallet, str(mint.pubkey()), 'USDC', 'creator', '772156', 'creator_wallet_all_tokens',
             base64.b64encode(bytes(original)).decode(), int(time.time())))
    phantom = PrivateKey.generate(); pk = mobile.b58enc(bytes(phantom.public_key))
    mobile.remember_authenticated_session(d.DB_FILE, os.environ['ENCRYPTION_KEY'], wallet,
        {'wallet_address': wallet, 'sk': bytes(phantom), 'phantom_pk': pk, 'session': 'mock-session'})
    client = app.test_client(); guest = app.test_client()
    with client.session_transaction() as sess:
        sess['wallet'] = wallet; sess['csrf_token'] = 'test-csrf'
    h = {'X-CSRF-Token': 'test-csrf'}
    ready = client.post('/api/token-launch/' + launch + '/claim/phantom/start', json={'claim_id': claim_id}, headers=h)
    q = {k: v[0] for k, v in parse_qs(urlparse(ready.get_json()['url']).query).items()}
    callback = parse_qs(urlparse(q['redirect_link']).query)
    relayed = []
    def relay(raw, signature, endpoints, **kw):
        relayed.append((raw, signature)); return True
    reply = make_reply(phantom, q['dapp_encryption_public_key'], {'transaction': mobile.b58enc(bytes(wrapped))})
    with patch('launch_delivery.relay_identical_signed', side_effect=relay):
        result = guest.post('/api/phantom-launch/complete', json={'token': callback['token'][0], 'step': 'sign', **reply})
    check('Phantom callback with the wrapped, signed claim is accepted (was 409 "did not match")',
          result.status_code == 200 and result.get_json().get('submitted'))
    check('...and exactly that signed transaction is relayed to Solana',
          len(relayed) == 1 and relayed[0][0] == bytes(wrapped) and relayed[0][1] == str(wrapped.signatures[0]))
    with sqlite3.connect(d.DB_FILE) as db:
        st = db.execute('SELECT status,signature FROM token_reward_claims WHERE id=?', (claim_id,)).fetchone()
    check('...and the claim is recorded as submitted with its signature', st == ('submitted', str(wrapped.signatures[0])))
    with patch('launch_delivery.relay_identical_signed', side_effect=relay):
        retry = client.post('/api/token-launch/' + launch + '/claim/phantom/retry-delivery', json={'claim_id': claim_id}, headers=h)
    check('re-delivery of the wrapped claim works too', retry.status_code == 200 and len(relayed) == 2)
raise SystemExit(0 if all(checks) else 1)
