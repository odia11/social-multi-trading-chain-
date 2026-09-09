"""/api/instant-trade — Live Market's one-click Solana buy and sell.

This endpoint built its own subprocess call instead of going through
_execute_user_swap_ex(), and that one shortcut cost it three things every
other Solana trade in the app gets:

  the gas guarantee. _ensure_solana_gas() is described in the code as the one
  place a wallet's ability to pay Solana's own network fee is assured, and
  every Solana buy and sell funnels through it -- except this one, the
  busiest of them;

  the right fee recipient. It sent fees to FEE_WALLET directly rather than
  _sol_fee_recipient(), so while the Solana gas sponsor was below target this
  was the only path not feeding it;

  the security log. It called decrypt_private_key() itself rather than
  _use_key(), so a key access from the app's busiest trade route was the one
  that never got logged.

Plus the two defects the other Solana buys had: a fee recorded whether or not
it was collected, and no guard against a double-click. And one of its own: a
partial sell zeroed the whole holding.
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

WALLET = 'W_INSTANT'
MINT = 'So11111111111111111111111111111111111111112'

conn = sqlite3.connect(d.DB_FILE)
conn.execute('INSERT OR IGNORE INTO users (wallet_address) VALUES (?)', (WALLET,))
conn.execute("UPDATE users SET encrypted_private_key='ENC' WHERE wallet_address=?", (WALLET,))
conn.commit()
uid = conn.execute('SELECT id FROM users WHERE wallet_address=?', (WALLET,)).fetchone()[0]
conn.close()
assert uid

d._authenticated_wallet = lambda: WALLET
d.fetch_user_balances = lambda w: None
d.get_user_state = lambda w: {'sol': 1.0, 'positions': {}}
# Solana trades are funded with USDC now, so the route reads a USDC balance on
# the TRADING wallet -- which it derives from the stored key. Both are real
# calls this probe has no network or key for.
d._get_trading_wallet_address = lambda w: 'TrAdInG1111111111111111111111111111111111111'
USDC_BAL = [500.0]
d._get_solana_usdc_balance = lambda addr: USDC_BAL[0]
d.add_user_log = lambda *a, **k: None
d._dex_get = lambda *a, **k: None

KEY_USES = []
class FakeKey:
    def __enter__(self):
        KEY_USES.append(1)
        return 'PK'
    def __exit__(self, *a): return False
d._use_key = lambda blob, wallet: FakeKey()

SWAPS, FEES = [], []
SWAP_RESULT = [(True, '0xSIG', '', 1234.5, 0.049)]
FEE_BUNDLED = [True]
SWAP_DELAY = [0.0]
def fake_swap(wallet, pk, action, mint, amount_str, base='SOL', capture=None):
    SWAPS.append({'action': action, 'mint': mint, 'amount': amount_str})
    time.sleep(SWAP_DELAY[0])
    if capture is not None:
        capture['fee_bundled'] = FEE_BUNDLED[0]
    return SWAP_RESULT[0]
d._execute_user_swap_ex = fake_swap

def fake_fee(pk, wallet, user_id, symbol, sol_amount, kind, bundled=False, **kw):
    FEES.append({'sol': sol_amount, 'kind': kind, 'bundled': bundled})
d._charge_txn_fee = fake_fee

def reset():
    SWAPS.clear(); FEES.clear(); KEY_USES.clear()
    d._recent_solana_buys.clear()

def post(body, keep_window=False):
    with d._rl_lock:
        d._rl_hits.clear()
    if not keep_window:
        d._recent_solana_buys.clear()
    r = c.post('/api/instant-trade', json=body)
    return r.status_code, r.get_json()

def tokens_row():
    conn = sqlite3.connect(d.DB_FILE)
    try:
        return conn.execute('SELECT amount FROM user_tokens WHERE user_id=? AND '
                            'token_address=?', (uid, MINT)).fetchone()
    finally:
        conn.close()

BUY = {'symbol': 'BONK', 'token_address': MINT, 'side': 'buy', 'amount_sol': 0.05}

# ── a buy ──
reset()
out['buy_status'], out['buy'] = post(BUY)
out['buy_swaps'] = list(SWAPS)
out['buy_fees'] = list(FEES)
out['buy_key_uses'] = len(KEY_USES)
out['tokens_after_buy'] = tokens_row()

# ── it goes through the shared wrapper, so it gets the gas guarantee ──
reset()
d._execute_user_swap_ex = lambda *a, **k: (False, '', 'no SOL for network fees', 0.0, 0.0)
out['nogas_status'], out['nogas'] = post(BUY)
d._execute_user_swap_ex = fake_swap

# ── the fee is recorded only when it was taken ──
reset()
FEE_BUNDLED[0] = False
out['nofee_status'], out['nofee'] = post(BUY)
out['nofee_fees'] = list(FEES)
FEE_BUNDLED[0] = True

# ── two clicks ──
reset()
SWAP_DELAY[0] = 0.4
results = []
def press():
    results.append(post(BUY, keep_window=True))
ts = [threading.Thread(target=press) for _ in range(2)]
for t in ts: t.start()
for t in ts: t.join()
SWAP_DELAY[0] = 0.0
out['double_swaps'] = len(SWAPS)
out['double_codes'] = sorted(r[0] for r in results)

# ── a failed buy releases the window ──
reset()
SWAP_RESULT[0] = (False, '', 'Jupiter route not found', 0.0, 0.0)
out['fail_status'], out['fail'] = post(BUY)
out['fail_window_held'] = (WALLET, MINT) in d._recent_solana_buys
SWAP_RESULT[0] = (True, '0xSIG', '', 1234.5, 0.049)

# ── a swap that returns no signature ──
reset()
SWAP_RESULT[0] = (True, '', '', 1234.5, 0.049)
out['nosig_status'], out['nosig'] = post(BUY)
SWAP_RESULT[0] = (True, '0xSIG', '', 1234.5, 0.049)

# ── two balances, two jobs ──
# SOL pays the network fee; USDC funds the trade. A check that conflates them
# tells the user the wrong currency is short.
reset()
d.get_user_state = lambda w: {'sol': 0.001, 'positions': {}}
out['nofee_sol_status'], out['nofee_sol'] = post(BUY)
out['nofee_sol_swaps'] = len(SWAPS)
d.get_user_state = lambda w: {'sol': 1.0, 'positions': {}}

reset()
USDC_BAL[0] = 0.02          # plenty of SOL for fees, nothing to trade with
out['nousdc_status'], out['nousdc'] = post(BUY)
out['nousdc_swaps'] = len(SWAPS)
USDC_BAL[0] = 500.0
# Solana trades are funded with USDC now, so the route reads a USDC balance on
# the TRADING wallet -- which it derives from the stored key. Both are real
# calls this probe has no network or key for.
d._get_trading_wallet_address = lambda w: 'TrAdInG1111111111111111111111111111111111111'
USDC_BAL = [500.0]
d._get_solana_usdc_balance = lambda addr: USDC_BAL[0]

# ── a FULL sell zeroes the holding ──
reset()
out['sell_status'], out['sell'] = post({'symbol': 'BONK', 'token_address': MINT,
                                        'side': 'sell'})
out['sell_swaps'] = list(SWAPS)
out['sell_fees'] = list(FEES)
out['tokens_after_full_sell'] = tokens_row()

# ── a PARTIAL sell must not ──
conn = sqlite3.connect(d.DB_FILE)
conn.execute('UPDATE user_tokens SET amount=0.05 WHERE user_id=? AND token_address=?',
             (uid, MINT))
conn.commit(); conn.close()
reset()
out['partial_status'], out['partial'] = post({'symbol': 'BONK', 'token_address': MINT,
                                              'side': 'sell', 'amount_token': 500})
out['partial_swaps'] = list(SWAPS)
out['tokens_after_partial'] = tokens_row()

# ── refusals ──
out['badside_status'], _ = post({'symbol': 'X', 'token_address': MINT, 'side': 'hold'})
out['nomint_status'], _   = post({'symbol': 'X', 'side': 'buy', 'amount_sol': 1})
out['zero_status'], _     = post({'symbol': 'X', 'token_address': MINT,
                                  'side': 'buy', 'amount_sol': 0})

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

# ── the buy ──
b = R['buy']
check('the buy succeeds', R['buy_status'] == 200 and b['success'])
check('it goes through the SHARED swap wrapper — the same one every other Solana '
      'trade uses, which is what gets it the network-fee guarantee it used to '
      'skip', len(R['buy_swaps']) == 1 and R['buy_swaps'][0]['action'] == 'buy')
check('...with the amount and mint from the request',
      R['buy_swaps'][0]['amount'] == '0.05' and R['buy_swaps'][0]['mint'])
check('the key is taken through _use_key, so this trade route now reaches the '
      'security log like every other one does', R['buy_key_uses'] >= 1)
check('the realized fill comes back rather than being re-parsed by hand',
      b['token_amount'] == 1234.5)
check('the fee is recorded as bundled, on the SOL spent',
      len(R['buy_fees']) == 1 and R['buy_fees'][0]['bundled'] is True
      and abs(R['buy_fees'][0]['sol'] - 0.05) < 1e-9)
check('...and the holding is credited', R['tokens_after_buy'])

check('a wallet that cannot pay the network fee now fails with the wrapper\'s own '
      'reason instead of a raw swap error — that check lives in the wrapper it '
      'used to bypass',
      R['nogas_status'] == 500 and 'network fees' in R['nogas']['error'])

# ── the fee ──
check('a swap that went through WITHOUT the platform fee records no fee. Both '
      'legs can fall back to a fee-less swap, and this asserted bundled=True '
      'regardless — writing a fees row and paying a 20% referral cut on money '
      'nobody collected',
      R['nofee_status'] == 200 and R['nofee_fees'] == []
      and R['nofee']['fee_collected'] is False)

# ── double click ──
check('two clicks at the same moment produce exactly ONE swap',
      R['double_swaps'] == 1 and R['double_codes'] == [200, 429])
check('a buy that FAILED releases the repeat window, so a retry is not blocked '
      'for something that never happened', R['fail_window_held'] is False)
check('...and reports the real reason', 'Jupiter route' in R['fail']['error'])
check('a swap with no signature is a failure, never a reported trade',
      R['nosig_status'] == 500 and 'no signature' in R['nosig']['error'])
check('too little SOL is refused as a NETWORK FEE problem, and says so — the '
      'trade itself is not funded in SOL any more, so naming SOL as the trading '
      'currency would send the user to buy the wrong thing',
      R['nofee_sol_status'] == 400 and R['nofee_sol_swaps'] == 0
      and 'network fees' in R['nofee_sol']['error']
      and 'funded with USDC' in R['nofee_sol']['error'])
check('too little USDC is a separate refusal, naming USDC and what to send',
      R['nousdc_status'] == 400 and R['nousdc_swaps'] == 0
      and 'Not enough USDC' in R['nousdc']['error']
      and 'SOL is only used for network fees' in R['nousdc']['error'])

# ── sells ──
s = R['sell']
check('a full sell succeeds and reports what it received',
      R['sell_status'] == 200 and s['success'] and s['sol_amount'] == 0.049)
check('...charging the fee on the SOL actually received',
      len(R['sell_fees']) == 1 and abs(R['sell_fees'][0]['sol'] - 0.049) < 1e-9
      and R['sell_fees'][0]['kind'] == 'sell')
check('...and zeroing the holding', R['tokens_after_full_sell'][0] == 0)

check('a PARTIAL sell still sells', R['partial_status'] == 200
      and R['partial_swaps'][0]['amount'] == '500.0')
check('...but does NOT zero the holding. Selling a slice used to make the rest '
      'of the position vanish from the portfolio while the tokens were still in '
      'the wallet', R['tokens_after_partial'][0] != 0)

check('a bad side is refused', R['badside_status'] == 400)
check('a missing token is refused', R['nomint_status'] == 400)
check('a zero-amount buy is refused', R['zero_status'] == 400)

# ── no third copy of the subprocess pattern ──
import ast                                                        # noqa: E402
src = open(REPO + '/dashboard.py').read()
tree = ast.parse(src)
fn = next(n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef) and n.name == 'api_instant_trade')
names = {c.func.id for c in ast.walk(fn)
         if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
attrs = {c.func.attr for c in ast.walk(fn)
         if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
check('it no longer runs its own swap subprocess — that was a third copy of the '
      'pattern, and copying it is how it drifted out of reach of the gas check',
      'run' not in attrs and '_execute_user_swap_ex' in names)
check('...and no longer decrypts the key itself',
      'decrypt_private_key' not in names and '_use_key' in names)

# The shared names it borrows are defined ABOVE it, not 5000 lines below.
order = {n.name: n.lineno for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
assigns = {t.id: n.lineno for n in ast.walk(tree) if isinstance(n, ast.Assign)
           for t in n.targets if isinstance(t, ast.Name)}
# `_recent_solana_buys: dict = {}` is an AnnAssign, not an Assign.
assigns.update({n.target.id: n.lineno for n in ast.walk(tree)
                if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)})
check('every shared helper and constant it uses is defined above it. Globals '
      'resolve at call time so the other order would still run, but that is '
      'exactly the shape of the definition-order bug that took the site down '
      'once already',
      all(pos < order['api_instant_trade'] for pos in
          (order['_get_solana_buy_lock'], order['_get_sell_lock'],
           assigns['SOL_NETWORK_RESERVE'], assigns['SOLANA_BUY_REPEAT_WINDOW'],
           assigns['_recent_solana_buys'])))

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
