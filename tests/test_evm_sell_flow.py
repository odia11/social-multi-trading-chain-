"""/api/evm/trade/sell and /api/bsc/trade/sell — one flow, three fixes.

These were two copies of the same function with the chain hardcoded in one,
and both carried the same three defects:

  a failed sell answered ok:true, so a caller checking `ok` read it as a
  success;

  two rapid clicks both read the same open position and both sold it;

  the exit price written into the trade history came from DexScreener, not
  from the swap, so the user's own record showed a price they did not get.

The sells are deliberately NOT on the trade engine -- it prices a spend
against a ceiling and a sell has no spend -- so what is checked here is that
the three defects are gone and that nothing around them was lost.
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

WALLET, EVM = 'W_SELL', '0xcccccccccccccccccccccccccccccccccccccccc'
TOKEN = '0xdddddddddddddddddddddddddddddddddddddddd'
conn = sqlite3.connect(d.DB_FILE)
conn.execute('INSERT OR IGNORE INTO users (wallet_address) VALUES (?)', (WALLET,))
conn.execute("UPDATE users SET bsc_wallet_address=?, encrypted_private_key_bsc='ENC' "
             'WHERE wallet_address=?', (EVM, WALLET))
conn.commit()
uid = conn.execute('SELECT id FROM users WHERE wallet_address=?', (WALLET,)).fetchone()[0]
conn.close()
assert uid

d._authenticated_wallet = lambda: WALLET
d.get_token_data = lambda a: {'symbol': 'PEPE', 'price': 0.02}
d._ensure_evm_gas = lambda *a, **k: (True, '', None)
d._recalculate_badges = lambda w: None

class FakeAcct:
    address = EVM
d._EvmAccount = type('A', (), {'from_key': staticmethod(lambda pk: FakeAcct())})

class FakeKey:
    def __enter__(self): return 'PK'
    def __exit__(self, *a): return False
d._use_key = lambda blob, wallet: FakeKey()

# One open position, closed by _close_open_position the way the app does.
POSITION = {'amount': 1000.0, 'buy_price': 0.01, 'spend': 10.0,
            'symbol': 'PEPE', 'opened_at': time.time()}
STATE = {'positions': {TOKEN: dict(POSITION)}}
d.get_user_state = lambda w: STATE
def close_pos(user_id, wallet, token, chain=None):
    STATE['positions'].pop(token, None)
d._close_open_position = close_pos

SELLS, FEES = [], []
SELL_RESULT = [(True, '', '0xSOLD')]
SELL_DELAY = [0.0]
def fake_swap(wallet, pk, action, token, amount_str, chain='bsc'):
    SELLS.append({'action': action, 'amount': amount_str, 'chain': chain})
    time.sleep(SELL_DELAY[0])
    return SELL_RESULT[0]
d._execute_evm_swap = fake_swap
d._execute_bsc_swap = lambda w, pk, a, t, amt: fake_swap(w, pk, a, t, amt, 'bsc')
def fake_fee(pk, wallet, user_id, symbol, usdc_amount, kind, chain='bsc', **kw):
    FEES.append({'usdc': usdc_amount, 'kind': kind, 'profit': kw.get('gross_profit')})
d._charge_evm_txn_fee = fake_fee

# The wallet gains $25 of USDC across the swap: 1000 tokens at $0.025, which
# is NOT the $0.02 DexScreener is quoting.
BALANCES = [0.0, 25.0]
BAL_CALLS = [0]
def fake_balance(addr, chain='bsc'):
    i = min(BAL_CALLS[0], len(BALANCES) - 1)
    BAL_CALLS[0] += 1
    return BALANCES[i]
d.get_evm_usdc_balance = fake_balance

def reset(positions=True):
    if positions:
        STATE['positions'][TOKEN] = dict(POSITION)
    SELLS.clear(); FEES.clear(); BAL_CALLS[0] = 0

def sell(body=None, path='/api/evm/trade/sell'):
    with d._rl_lock:
        d._rl_hits.clear()
    r = c.post(path, json=body if body is not None
               else {'chain': 'base', 'token_address': TOKEN})
    return r.status_code, r.get_json()

def trade_rows():
    conn = sqlite3.connect(d.DB_FILE)
    try:
        return conn.execute(
            'SELECT exit_price, amount, pnl, fee_amount, chain FROM trades '
            'WHERE user_id=? ORDER BY id DESC LIMIT 1', (uid,)).fetchone()
    finally:
        conn.close()

# ── the happy path, with a real measured exit price ──
reset()
out['sell_status'], out['sell'] = sell()
out['sells'] = list(SELLS)
out['fees'] = list(FEES)
out['row'] = trade_rows()
out['position_left'] = TOKEN in STATE['positions']

# ── selling nothing ──
out['none_status'], out['none'] = sell()

# ── a failed sell ──
reset()
SELL_RESULT[0] = (False, 'Swap transaction reverted on-chain', '0xREVERT')
out['fail_status'], out['fail'] = sell()
out['fail_position_kept'] = TOKEN in STATE['positions']

# ── a sell that was sent but never confirmed ──
reset()
SELL_RESULT[0] = (False, d.SWAP_UNCONFIRMED_PREFIX + ': sent but not confirmed within 90s',
                  '0xUNKNOWN')
out['unconf_status'], out['unconf'] = sell()
out['unconf_position_kept'] = TOKEN in STATE['positions']
SELL_RESULT[0] = (True, '', '0xSOLD')

# ── two clicks at once ──
reset()
SELL_DELAY[0] = 0.4
results = []
def press():
    with d.app.test_request_context():
        pass
    results.append(sell())
threads = [threading.Thread(target=press) for _ in range(2)]
for t in threads: t.start()
for t in threads: t.join()
SELL_DELAY[0] = 0.0
out['double_swaps'] = len([s for s in SELLS if s['action'] == 'sell'])
out['double_oks'] = sorted(bool((r[1] or {}).get('ok')) for r in results)

# ── the balance read failing falls back, and says so ──
reset()
def boom_balance(addr, chain='bsc'):
    raise RuntimeError('rpc down')
d.get_evm_usdc_balance = boom_balance
out['est_status'], out['est'] = sell()
d.get_evm_usdc_balance = fake_balance

# ── the BSC route ──
reset()
out['bsc_status'], out['bsc'] = sell({'token_address': TOKEN},
                                     path='/api/bsc/trade/sell')
out['bsc_sells'] = list(SELLS)

# ── an unsupported chain ──
out['badchain_status'], out['badchain'] = sell({'chain': 'ethereum',
                                                'token_address': TOKEN})

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

# ── the sell works, and the position closes ──
sl = R['sell']
check('the sell succeeds', R['sell_status'] == 200 and sl['ok'] and sl['sell_executed'])
check('exactly one swap goes out, for the whole tracked position',
      len(R['sells']) == 1 and float(R['sells'][0]['amount']) == 1000.0)
check('the position is closed afterwards', not R['position_left'])

# ── FIX 3: the exit price is measured, not quoted ──
check('the exit price is what the swap RETURNED ($25 for 1000 tokens = $0.025), '
      'not the $0.02 DexScreener was quoting — the old code wrote the market '
      "price into the user's own trade history as if it were realised",
      float(sl['exit_price']) == 0.025 and float(sl['proceeds_usdc']) == 25.0)
check('...and says it is a measured figure rather than an estimate',
      sl['exit_price_estimated'] is False)
check('the trade history row carries that same measured price',
      R['row'] and abs(float(R['row'][0]) - 0.025) < 1e-9)
check('the fee is taken on the real proceeds, not on a market-price guess',
      len(R['fees']) == 1 and float(R['fees'][0]['usdc']) == 25.0)
check('the profit follows from the measured price too — $0.025 out against '
      '$0.01 in on 1000 tokens is $15, where the quoted price would have said $10',
      abs(float(R['fees'][0]['profit']) - 15.0) < 1e-6)

est = R['est']
check('when the balance cannot be read the sell still completes on the market '
      'price rather than failing', R['est_status'] == 200 and est['ok'])
check('...but is LABELLED estimated, so a guess is never passed off as the '
      'realised price', est['exit_price_estimated'] is True
      and float(est['exit_price']) == 0.02)

# ── FIX 1: a failed sell says so ──
f = R['fail']
check('a sell that reverted answers ok:false. It used to answer ok:true with '
      "sell_executed:false, so a caller checking `ok` — what every other route "
      'on this app means by success — read a failed sell as a success',
      R['fail_status'] == 502 and f['ok'] is False and f['sell_executed'] is False)
check('...with the reason and the hash', 'reverted' in f['msg'] and f['tx_hash'] == '0xREVERT')
check('...and the position is KEPT, because the tokens are still there',
      R['fail_position_kept'])

u = R['unconf']
check('a sell that was sent but never confirmed also answers ok:false',
      R['unconf_status'] == 502 and u['ok'] is False)
check('...marked unconfirmed and keeping its hash, so it can be traced',
      u['unconfirmed'] is True and u['tx_hash'] == '0xUNKNOWN')
check('...and keeps the position: closing one for a swap nobody has seen land '
      'would hide a holding the user still owns', R['unconf_position_kept'])

# ── FIX 2: no double sell ──
check('two clicks at the same moment produce exactly ONE swap — both used to '
      'read the same open position and both sold it', R['double_swaps'] == 1)
check('...and the loser is told there is no open position rather than being '
      'reported a second sale', R['double_oks'] == [False, True])

check('selling a token with no open position is refused',
      R['none_status'] == 400 and 'No open position' in R['none']['msg'])

# ── the BSC route runs the same flow ──
check('the BSC sell gets all three fixes at the same moment, because it is now '
      'the same code rather than a copy',
      R['bsc_status'] == 200 and R['bsc']['ok']
      and R['bsc']['exit_price_estimated'] is False
      and R['bsc_sells'][0]['chain'] == 'bsc')
check('a chain the platform does not trade is still refused',
      R['badchain_status'] == 400 and 'ethereum' in R['badchain']['msg'])

# ── one implementation ──
import ast                                                        # noqa: E402
src = open(REPO + '/dashboard.py').read()
tree = ast.parse(src)
funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
for name in ('api_evm_trade_sell', 'api_bsc_trade_sell'):
    calls = {c.func.id for c in ast.walk(funcs[name])
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    check(f'{name} is a thin route over the shared flow, not its own copy',
          '_evm_sell_flow' in calls
          and not (calls & {'_execute_evm_swap', '_execute_bsc_swap',
                            '_charge_evm_txn_fee', '_charge_bsc_txn_fee'}))
flow = funcs['_evm_sell_flow']
check('the position is read inside the lock, not before it — reading it outside '
      'is what allowed the double sell',
      any(isinstance(n, ast.With) and any(
          isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
          and c.func.id == 'get_user_state' for c in ast.walk(n))
          for n in ast.walk(flow)))

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
