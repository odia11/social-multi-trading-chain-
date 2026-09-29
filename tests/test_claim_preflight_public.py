"""Every creator-fee claim is simulated before Phantom opens.

Only pilot wallets were simulated; everyone else's claim went straight to
Phantom, which answered "Unexpected error" (-32603) when the claim could not
succeed -- e.g. too little SOL for the creator's USDC receiving account rent
and the fee. Now:
- not enough SOL -> a clear message, no claim prepared, Phantom not opened;
- a claim that would fail on-chain -> refused before Phantom;
- an RPC that cannot answer -> the claim is still prepared (never blocked on a guess);
- the simulation replaces the blockhash, so a just-fetched one is not "not found".
Offline: mocked RPC and builder; nothing is signed or sent.
"""
import base64, json, os, sqlite3, sys, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.system_program import transfer, TransferParams
from solders.transaction import Transaction
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from test_token_launch import setup  # noqa: E402
import token_launch  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

class Reply:
    def __init__(self, result=None, code=200): self.status_code = code; self._r = result
    def json(self): return {'result': self._r}
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError('http ' + str(self.status_code))

tmp, app, d = setup(); client = app.test_client(); owner = Keypair()
wallet = str(owner.pubkey()); mint = str(Keypair().pubkey()); ident = '7' * 32
with sqlite3.connect(d.DB_FILE) as c:
    c.execute('''INSERT INTO token_launches (id,wallet,client_nonce,name,symbol,icon_webp,reward_mode,
        quote_asset,mint,status,launch_signature,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
        (ident, wallet, 'usdc-claim', 'Sunshine', 'SUN', b'icon', 'creator', 'USDC', mint, 'live', 'x' * 88, int(time.time())))
with client.session_transaction() as ss:
    ss['wallet'] = wallet; ss['csrf_token'] = 'test-csrf'
tx = Transaction.new_unsigned(Message.new_with_blockhash([transfer(TransferParams(
    from_pubkey=owner.pubkey(), to_pubkey=owner.pubkey(), lamports=0))], owner.pubkey(), Hash.default()))
raw = base64.b64encode(bytes(tx)).decode()
built = dict(mint=mint, quote_mint=token_launch.USDC_MINT, transaction_b64=raw, transaction_bytes=len(bytes(tx)),
             accrued_raw='772156', accrued_scope='creator_wallet_all_tokens', quote_asset='USDC')

mode = {'sim': 'ok'}
seen = []
def rpc(url, *, json, timeout):
    m = json['method']; seen.append((m, json.get('params')))
    if m == 'getLatestBlockhash': return Reply({'value': {'blockhash': str(Hash.default())}})
    if m == 'getSignaturesForAddress': return Reply([])
    if mode['sim'] == 'down' and m in ('getBalance', 'getFeeForMessage', 'simulateTransaction'):
        return Reply(code=503)
    if m == 'getBalance': return Reply({'value': 400_000 if mode['sim'] == 'poor' else 50_000_000})
    if m == 'getFeeForMessage': return Reply({'value': 5000})
    if m == 'simulateTransaction':
        if mode['sim'] == 'poor':
            return Reply({'value': {'err': {'InstructionError': [0, {'Custom': 1}]}, 'accounts': [None],
                          'logs': ['Program log: Transfer: insufficient lamports 400000, need 2039280']}})
        if mode['sim'] == 'fails':
            return Reply({'value': {'err': {'InstructionError': [2, {'Custom': 6000}]}, 'accounts': [None], 'logs': []}})
        return Reply({'value': {'err': None, 'accounts': [{'lamports': 47_955_720}]}})
    raise AssertionError(m)
def builder(args, **kwargs):
    return SimpleNamespace(returncode=0, stdout=json.dumps(built), stderr='')

def prepare():
    with sqlite3.connect(d.DB_FILE) as c:
        c.execute('DELETE FROM token_reward_claims')
    with patch.dict(os.environ, {'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED': '1'}), \
         patch('token_launch.requests.post', side_effect=rpc), \
         patch('token_launch.subprocess.run', side_effect=builder), patch('token_launch.time.sleep'):
        r = client.post('/api/token-launch/' + ident + '/claim/prepare', json={}, headers={'X-CSRF-Token': 'test-csrf'})
    with sqlite3.connect(d.DB_FILE) as c:
        n = c.execute('SELECT COUNT(*) FROM token_reward_claims').fetchone()[0]
    return r, n

mode['sim'] = 'poor'
r, n = prepare()
msg = (r.get_json() or {}).get('msg', '')
check('not enough SOL: a clear message instead of Phantom\'s "Unexpected error"',
      r.status_code != 200 and msg.startswith('Insufficient SOL') and '0.000400000 SOL' in msg and 'Add SOL' in msg)
check('...and no claim is prepared, so Phantom is not opened', n == 0)

mode['sim'] = 'fails'
r, n = prepare()
check('a claim that would fail on-chain is refused before Phantom',
      r.status_code != 200 and 'would fail on Solana' in r.get_json()['msg'] and n == 0)

mode['sim'] = 'down'
r, n = prepare()
check('an RPC that cannot answer does not block the claim', r.status_code == 200 and n == 1)

mode['sim'] = 'ok'; seen.clear()
r, n = prepare()
sim = [p for m, p in seen if m == 'simulateTransaction']
check('a healthy claim is prepared', r.status_code == 200 and n == 1)
check('...after a simulation that ignores the just-fetched blockhash',
      sim and sim[0][1].get('replaceRecentBlockhash') is True and sim[0][1].get('sigVerify') is False)
tmp.cleanup()
raise SystemExit(0 if all(checks) else 1)
