"""A Live Market buy answers as soon as the swap is confirmed on Solana.

Around the swap itself /api/instant-trade did three more network round trips
before the user saw "Bought":
- a SOL check on the LOGIN (Phantom) wallet -- the wrong wallet: a user whose
  SOL sat only in the trading wallet was refused with "Not enough SOL for
  network fees" -- on top of the trading-wallet check that already keeps the
  network reserve;
- a DexScreener lookup (up to 6 s) to price the buy, while the fill itself
  says what was paid: SOL spent / tokens received;
- a getBalance after the trade (up to 5 s per RPC), display-only and unused
  by the app.
Now: one balance read on the trading wallet, handed to the swap's gas check
so it is not read again; the buy is priced from the fill; no reads after.
Confirmation is polled every 0.25 s (was 0.4 s).
"""
import os, sqlite3, sys, tempfile, threading, time
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(), 'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_POSITION_GUARDIAN': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

WALLET = str(Keypair().pubkey()); MINT = str(Keypair().pubkey()); TRADING = str(Keypair().pubkey())
uid = d.get_or_create_user(WALLET)
with sqlite3.connect(d.DB_FILE) as c:
    c.execute("UPDATE users SET encrypted_private_key='ENC' WHERE id=?", (uid,))

network = []
balance_reads = []
ME = threading.get_ident()   # only calls made while serving the request count (background loops also use _dex_get)
d._get_trading_wallet_address = lambda w: TRADING
def fake_sol(addr):
    balance_reads.append(addr); return 1.0
d._get_user_sol = fake_sol
d.fetch_user_balances = lambda w: network.append(('login-wallet balance', w))
d._dex_get = lambda *a, **k: (network.append(('dexscreener', a[0] if a else '')) if threading.get_ident() == ME else None) or None
_real_post = d.requests.post
def fake_post(url, *a, **k):
    if threading.get_ident() == ME:
        network.append(('rpc', (k.get('json') or {}).get('method')))
    raise RuntimeError('no network in tests')
d.requests.post = fake_post
class FakeKey:
    def __enter__(self): return 'PK'
    def __exit__(self, *a): return False
d._use_key = lambda blob, wallet: FakeKey()
d.add_user_log = lambda *a, **k: None
d._charge_txn_fee = lambda *a, **k: None
swaps = []
def fake_swap(wallet, pk, action, mint, amount_str, base='SOL', capture=None, known_sol_balance=None, fee_rate=None):
    swaps.append({'action': action, 'known_sol_balance': known_sol_balance})
    if capture is not None:
        capture['fee_bundled'] = True
    return True, 'SIG' + str(len(swaps)), '', 1000.0, 0.5   # 1000 tokens for 0.5 SOL
d._execute_user_swap_ex = fake_swap
d._sol_price_usd = 150.0

client = app_entry.app.test_client()
with client.session_transaction(base_url='https://orcagent.fun') as s:
    s['wallet'] = WALLET; s['csrf_token'] = 'x' * 40
fee = int(round(d.PT_FEE_RATE_TXN * 10000)) if hasattr(d, 'PT_FEE_RATE_TXN') else None
body = {'symbol': 'BONK', 'token_address': MINT, 'side': 'buy', 'currency': 'SOL', 'amount_sol': 0.5}
if fee is not None:
    body['max_platform_fee_bps'] = fee
t0 = time.time()
r = client.post('/api/instant-trade', json=body, headers={'X-CSRF-Token': 'x' * 40}, base_url='https://orcagent.fun')
took = time.time() - t0
j = r.get_json() or {}
if r.status_code != 200:
    print('response', r.status_code, j)
check('the buy goes through', r.status_code == 200 and (j.get('success') or j.get('tx')))
check('no SOL check on the login wallet (the wrong wallet, and an extra round trip)',
      not any(kind == 'login-wallet balance' for kind, _ in network))
check('one balance read, on the trading wallet', balance_reads == [TRADING])
check('...handed to the swap so its gas check does not read it again', swaps and swaps[0]['known_sol_balance'] == 1.0)
check('no DexScreener lookup and no balance read after the swap', not any(kind in ('dexscreener', 'rpc') for kind, _ in network))
check('the response comes straight away (%.2fs)' % took, took < 1.0)
pos = d.get_user_state(WALLET).get('positions', {}).get(MINT) or {}
with sqlite3.connect(d.DB_FILE) as c:
    row = c.execute('SELECT avg_price FROM user_tokens WHERE user_id=? AND token_address=?', (uid, MINT)).fetchone()
price = row[0] if row else None
check('the buy is priced from the fill: 0.5 SOL x $150 / 1000 tokens = $0.075', price is not None and abs(price - 0.075) < 1e-9)
src = open(os.path.join(ROOT, 'orcagent_solana.py'), encoding='utf-8').read()
check('confirmation is polled every 0.25 s', 'CONFIRM_POLL_INTERVAL_S = 0.25' in src)
d.requests.post = _real_post
raise SystemExit(0 if all(checks) else 1)
