"""/api/manual_buy and /api/pump-scanner/buy — one flow, three fixes.

These were two copies of the same Solana buy differing only in the field the
mint arrives under, a five-position cap, and their log wording. Three things
were wrong in both, so they were wrong in neither's tests:

  the wallet could be spent down to zero, leaving a position that could not
  be sold because there was no SOL left to pay for the sell;

  two clicks both read the balance and both bought, and the position is
  additive, so the second one really did spend again;

  the platform fee was recorded whether or not it was collected -- the swap
  falls back to a fee-less buy if bundling fails, and the app then wrote a
  fees row and paid a 20% referral cut on money nobody received.

Worth stating because the rest of this phase was about the opposite bug: the
fee itself was already correct here. A bundled Solana buy swaps (spend - fee)
so the wallet spends exactly what was asked. It is the EVM path that charged
on top.
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = '/home/user/Orc-agent-Solana-chain-'

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


PROBE = r'''
import json, sqlite3, threading, time, sys
import dashboard as d

out = {}
d.app.config['TESTING'] = True
c = d.app.test_client()

WALLET = 'W_SOL'
MINT = 'So11111111111111111111111111111111111111112'
TRADING = 'TrAdInG1111111111111111111111111111111111111'

conn = sqlite3.connect(d.DB_FILE)
conn.execute('INSERT OR IGNORE INTO users (wallet_address) VALUES (?)', (WALLET,))
conn.execute("UPDATE users SET encrypted_private_key='ENC', min_trade_size=1 "
             'WHERE wallet_address=?', (WALLET,))
conn.commit()
uid = conn.execute('SELECT id FROM users WHERE wallet_address=?', (WALLET,)).fetchone()[0]
conn.close()
assert uid

d._authenticated_wallet = lambda: WALLET
d._sol_price_usd = 100.0
d.get_token_data = lambda m: {'symbol': 'BONK', 'price': 0.001, 'liquidity': 50000}
d._snapshot_entry_risk = lambda w, p: {}
d._trigger_copy_buy = lambda *a, **k: None
d.add_user_log = lambda *a, **k: None
d._record_ip_failure = lambda ip: None

class FakeKey:
    def __enter__(self): return '5' * 60
    def __exit__(self, *a): return False
d._use_key = lambda blob, wallet: FakeKey()

import types
fake_solders = types.ModuleType('solders.keypair')
class _KP:
    @staticmethod
    def from_base58_string(pk):
        return types.SimpleNamespace(pubkey=lambda: TRADING)
fake_solders.Keypair = _KP
sys.modules['solders.keypair'] = fake_solders

STATE = {'positions': {}, 'trader_running': False}
d.get_user_state = lambda w: STATE
POSITIONS = []
def upsert(user_id, wallet, mint, pos, source=None, chain=None):
    POSITIONS.append(dict(pos))
    STATE['positions'][mint] = dict(pos)
d._upsert_open_position = upsert

SOL = [1.0]
d._get_user_sol = lambda addr: SOL[0]

BUYS, FEES = [], []
BUY_OK = [True]
FEE_BUNDLED = [True]
BUY_DELAY = [0.0]
def fake_buy(wallet, pk, mint, spend, price, base='SOL', capture=None):
    BUYS.append({'spend': spend, 'mint': mint})
    time.sleep(BUY_DELAY[0])
    if capture is not None:
        capture['fee_bundled'] = FEE_BUNDLED[0]
    if not BUY_OK[0]:
        return False, price, 0.0
    return True, 0.0012, spend / 0.0012
d._buy_and_get_realized = fake_buy
def fake_fee(pk, wallet, user_id, symbol, sol_amount, kind, bundled=False, **kw):
    FEES.append({'sol': sol_amount, 'kind': kind, 'bundled': bundled})
d._charge_txn_fee = fake_fee

def reset():
    BUYS.clear(); FEES.clear(); POSITIONS.clear()
    STATE['positions'] = {}

def buy(body=None, path='/api/manual_buy', keep_window=False):
    with d._rl_lock:
        d._rl_hits.clear()
    if not keep_window:
        # Each case here is a fresh decision, not a double-click; the window
        # itself is exercised on purpose further down.
        d._recent_solana_buys.clear()
    r = c.post(path, json=body if body is not None else {'mint_address': MINT})
    return r.status_code, r.get_json()

# ── the happy path: 1 USDC / $100 per SOL = 0.01 SOL ──
reset()
out['buy_status'], out['buy'] = buy()
out['buys'] = list(BUYS)
out['fees'] = list(FEES)

# ── FIX 1: SOL is kept back for fees ──
reset()
SOL[0] = 0.012          # less than the 0.01 wanted plus the 0.005 reserve
out['tight_status'], out['tight'] = buy()
out['tight_buys'] = list(BUYS)

reset()
SOL[0] = 0.011          # 0.011 - 0.005 = 0.006 spendable
out['reserve_status'], out['reserve'] = buy()
out['reserve_buys'] = list(BUYS)

reset()
SOL[0] = 0.009          # below reserve + minimum spend
out['broke_status'], out['broke'] = buy()
out['broke_buys'] = len(BUYS)

SOL[0] = 1.0

# ── FIX 3: the fee is recorded only when it was taken ──
reset()
FEE_BUNDLED[0] = False
out['nofee_status'], out['nofee'] = buy()
out['nofee_fees'] = list(FEES)
FEE_BUNDLED[0] = True

# ── FIX 2: two clicks, one buy ──
reset()
BUY_DELAY[0] = 0.4
d._recent_solana_buys.clear()
results = []
def press():
    results.append(buy(keep_window=True))
ts = [threading.Thread(target=press) for _ in range(2)]
for t in ts: t.start()
for t in ts: t.join()
BUY_DELAY[0] = 0.0
out['double_buys'] = len(BUYS)
out['double_spend'] = sum(b['spend'] for b in BUYS)
out['double_codes'] = sorted(r[0] for r in results)

# ── a deliberate second buy, after the window ──
reset()
d._recent_solana_buys.clear()
buy()
d._recent_solana_buys[(WALLET, MINT)] -= d.SOLANA_BUY_REPEAT_WINDOW + 1
out['later_status'], out['later'] = buy(keep_window=True)
out['later_buys'] = len(BUYS)

# ── a failed buy does not hold the window ──
reset()
d._recent_solana_buys.clear()
BUY_OK[0] = False
buy()
out['after_fail_held'] = (WALLET, MINT) in d._recent_solana_buys
BUY_OK[0] = True

# ── a failed buy opens no position ──
reset()
BUY_OK[0] = False
out['fail_status'], out['fail'] = buy()
out['fail_positions'] = len(POSITIONS)
out['fail_fees'] = len(FEES)
BUY_OK[0] = True

# ── the pump scanner route, same flow ──
reset()
out['pump_status'], out['pump'] = buy({'mint': MINT}, path='/api/pump-scanner/buy')
out['pump_buys'] = list(BUYS)

# ── the position cap applies to manual_buy only ──
reset()
STATE['positions'] = {('M%02d' % i): {'amount': 5.0} for i in range(5)}
out['cap_status'], out['cap'] = buy()
out['cap_buys'] = len(BUYS)
reset()
STATE['positions'] = {('M%02d' % i): {'amount': 5.0} for i in range(5)}
out['pumpcap_status'], out['pumpcap'] = buy({'mint': MINT}, path='/api/pump-scanner/buy')
out['pumpcap_buys'] = len(BUYS)
STATE['positions'] = {}

# ── a bad mint ──
out['badmint_status'], out['badmint'] = buy({'mint_address': 'not-a-mint'})

out['reserve_const'] = d.SOL_NETWORK_RESERVE
print('__RESULT__' + json.dumps(out, default=str))
'''

from cryptography.fernet import Fernet
env = dict(os.environ)
env.update({'ENCRYPTION_KEY': Fernet.generate_key().decode(),
            'SECRET_KEY': 'test-only', 'DATA_DIR': tempfile.mkdtemp()})
res = subprocess.run([sys.executable, '-c', PROBE], cwd=REPO, env=env,
                     capture_output=True, text=True, timeout=300)
line = next((l for l in res.stdout.split('\n') if l.startswith('__RESULT__')), None)
if not line:
    print(res.stdout[-4000:]); print(res.stderr[-4000:])
    check('the probe ran at all', False)
    sys.exit(1)
R = json.loads(line[len('__RESULT__'):])

# ── the buy works ──
b = R['buy']
check('the buy succeeds', R['buy_status'] == 200 and b['ok'])
check('it spends the configured trade size — $1 at $100/SOL is 0.01 SOL',
      len(R['buys']) == 1 and abs(R['buys'][0]['spend'] - 0.01) < 1e-9)
check('the fee is recorded as bundled, taken inside the swap rather than as a '
      'second transfer the user would see leave their wallet',
      len(R['fees']) == 1 and R['fees'][0]['bundled'] is True
      and abs(R['fees'][0]['sol'] - 0.01) < 1e-9)
check('the response says the fee was collected', b['fee_collected'] is True)

# ── FIX 1 ──
check(f"a reserve of {R['reserve_const']} SOL is kept back", R['reserve_const'] == 0.005)
check('with 0.011 SOL the buy is capped at 0.006, not the 0.01 asked for — the old '
      'code spent min(size, whole balance) and could leave a wallet at zero, '
      'holding tokens it had no SOL left to sell',
      R['reserve_status'] == 200 and abs(R['reserve_buys'][0]['spend'] - 0.006) < 1e-9)
check('with 0.012 SOL it is capped at 0.007 for the same reason',
      abs(R['tight_buys'][0]['spend'] - 0.007) < 1e-9)
check('a balance below the reserve plus a worthwhile trade is refused rather '
      'than spent down to zero', R['broke_status'] == 400 and R['broke_buys'] == 0)
check('...and the refusal explains the reserve instead of just saying no. The '
      'floor is now derived from the reserve rather than a bare 0.01, so there '
      'is no band where the balance passes and nothing is left to spend',
      'kept back for network fees' in R['broke']['msg'])

# ── FIX 3 ──
check('a swap that went through WITHOUT the platform fee records no fee at all. '
      'Both copies used to write a fees row and pay a 20% referral cut on money '
      'nobody had collected',
      R['nofee_status'] == 200 and R['nofee']['ok'] and R['nofee_fees'] == [])
check('...and the response says so, since the fees table will have no row',
      R['nofee']['fee_collected'] is False)

# ── FIX 2 ──
check('two clicks at the same moment produce exactly ONE buy. A lock alone does '
      'not fix this the way it does for a sell: a sell finds the position gone '
      'and stops, but a buy is ADDITIVE, so serializing two clicks just makes '
      'both of them spend, in order', R['double_buys'] == 1)
check('...so the wallet spends 0.01 SOL once, not twice',
      abs(R['double_spend'] - 0.01) < 1e-9)
check('...and the loser is refused rather than being reported a second purchase',
      R['double_codes'] == [200, 429])
check('a deliberate second buy AFTER the window still goes through — buying more '
      'of a token you already hold is a legitimate thing to want, and only the '
      'few-seconds repeat is refused',
      R['later_status'] == 200 and R['later']['ok'] and R['later_buys'] == 2)
check('a buy that FAILED does not hold the window against the user, who would '
      'otherwise wait to retry something that never happened',
      R['after_fail_held'] is False)

# ── a failed buy ──
check('a failed buy opens no position and records no fee',
      R['fail_status'] == 500 and R['fail_positions'] == 0 and R['fail_fees'] == 0)

# ── both routes, one flow ──
check('the pump scanner buy runs the same flow, so all three fixes land on it too',
      R['pump_status'] == 200 and R['pump']['ok']
      and abs(R['pump_buys'][0]['spend'] - 0.01) < 1e-9
      and R['pump']['fee_collected'] is True)
check('the five-position cap still applies to the manual buy',
      R['cap_status'] == 400 and 'Max 5 positions' in R['cap']['msg']
      and R['cap_buys'] == 0)
check('...and still does NOT apply to the pump scanner, which is a deliberate '
      'pick outside the scoring algorithm',
      R['pumpcap_status'] == 200 and R['pumpcap_buys'] == 1)
check('an invalid mint is refused', R['badmint_status'] == 400)

# ── one implementation ──
import ast                                                        # noqa: E402
src = open(REPO + '/dashboard.py').read()
tree = ast.parse(src)
funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
for name in ('api_manual_buy', 'api_pump_scanner_buy'):
    calls = {c.func.id for c in ast.walk(funcs[name])
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    check(f'{name} is a thin route over the shared flow, not its own copy',
          '_solana_buy_flow' in calls
          and not (calls & {'_buy_and_get_realized', '_charge_txn_fee',
                            '_upsert_open_position'}))
flow = funcs['_solana_buy_flow']
check('the balance is read inside the lock, not before it — reading it outside is '
      'what allowed the double buy',
      any(isinstance(n, ast.With) and any(
          isinstance(cc, ast.Call) and isinstance(cc.func, ast.Name)
          and cc.func.id == '_get_user_sol' for cc in ast.walk(n))
          for n in ast.walk(flow)))

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
