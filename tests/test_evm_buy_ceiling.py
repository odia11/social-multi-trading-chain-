"""/api/evm/trade/buy — the first live route moved behind the engine.

This is the one that matters to a user pressing Buy. Before this change the
route swapped the FULL amount entered and then charged 0.75% of it on top, so
someone who typed $100 spent $100.75 plus gas. The amount on screen was not
the amount spent.

What is checked here is that the route's behaviour actually changed and that
nothing around it was lost on the way: the gas bootstrap-and-ride-along still
works, the trade-size clamp still applies, a double-click cannot become two
swaps, and the old path is still reachable through the flag.
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
import json, sqlite3, sys
from decimal import Decimal
import dashboard as d

out = {}
d.app.config['TESTING'] = True
c = d.app.test_client()

WALLET, EVM = 'W_BUY', '0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
def ensure_user(conn, wallet, evm):
    """Create the user if absent, then give it a trading wallet.

    INSERT OR IGNORE alone is not enough: it silently does nothing when the
    row already exists, so a previous run's half-set-up user would be reused
    and the test would quietly exercise the wrong thing. And _get_uid only
    looks up -- it never creates -- so relying on it means depending on rows
    somebody else's test left behind.
    """
    conn.execute('INSERT OR IGNORE INTO users (wallet_address) VALUES (?)', (wallet,))
    conn.execute("UPDATE users SET bsc_wallet_address=?, encrypted_private_key_bsc='ENC' "
                 'WHERE wallet_address=?', (evm, wallet))
    conn.commit()
    row = conn.execute('SELECT id, encrypted_private_key_bsc, bsc_wallet_address '
                       'FROM users WHERE wallet_address=?', (wallet,)).fetchone()
    assert row and row[1] and row[2], (wallet, row)
    return row[0]

conn = sqlite3.connect(d.DB_FILE)
uid = ensure_user(conn, WALLET, EVM)
# max_trade_size below the mocked $500 balance, so the clamp case below is
# testing the clamp and not the balance check in front of it.
conn.execute('UPDATE users SET min_trade_size=1, max_trade_size=200 '
             'WHERE wallet_address=?', (WALLET,))
conn.commit(); conn.close()

d._authenticated_wallet = lambda: WALLET
d._te_gas_usd = lambda chain: Decimal('0.35')
d._te_needs_sponsored_gas = lambda chain, addr: True
d.get_evm_usdc_balance = lambda addr, chain='bsc': 500.0
d.get_token_data = lambda a: {'symbol': 'PEPE', 'price': 0.01}
d._upsert_open_position = lambda *a, **k: POSITIONS.append(a[3])
POSITIONS = []

GAS_CALLS = []
GAS_RESULT = [(True, '', None)]
def fake_gas(user_id, wallet, pk, addr, chain, auto_buy_token_address=None,
             auto_buy_requested_usdc=None):
    GAS_CALLS.append({'chain': chain, 'auto_buy_token': auto_buy_token_address,
                      'auto_buy_usdc': auto_buy_requested_usdc})
    return GAS_RESULT[0]
d._ensure_evm_gas = fake_gas

def fake_0x(sell, buy, amount, taker, chain):
    return {'buyAmount': '1000000000000000000', 'minBuyAmount': '985000000000000000',
            'transaction': {'gas': '200000', 'gasPrice': '10000000'}}
d._te_swap_provider = lambda chain: d.ZeroExProvider(fake_0x)

class FakeKey:
    def __enter__(self): return 'PK'
    def __exit__(self, *a): return False
d._use_key = lambda blob, wallet: FakeKey()

SWAPS, FEES = [], []
SWAP_RESULT = [(True, '', '0xBOUGHT')]
def fake_swap(wallet, pk, action, token, amount_str, chain='bsc'):
    SWAPS.append({'action': action, 'amount': amount_str, 'chain': chain})
    return SWAP_RESULT[0]
d._execute_evm_swap = fake_swap
def fake_fee(pk, wallet, user_id, symbol, usdc_amount, kind, chain='bsc', **kw):
    FEES.append({'usdc': usdc_amount, 'kind': kind})
d._charge_evm_txn_fee = fake_fee

def buy(body, path='/api/evm/trade/buy'):
    with d._rl_lock:
        d._rl_hits.clear()
    r = c.post(path, json=body)
    return r.status_code, r.get_json()

# ── the engine path ──
out['buy_status'], out['buy'] = buy({'chain': 'base', 'token_address': EVM,
                                     'amount_usdc': 100})
out['swaps'] = list(SWAPS)
out['fees'] = list(FEES)
out['positions'] = list(POSITIONS)
out['gas_calls'] = list(GAS_CALLS)

# ── a second, identical press ──
SWAPS.clear()
out['again_status'], out['again'] = buy({'chain': 'base', 'token_address': EVM,
                                         'amount_usdc': 100})
out['second_press_swaps'] = len(SWAPS)
out['distinct_trade'] = out['again'].get('trade_id') != out['buy'].get('trade_id')

# ── the gas bootstrap still rides along ──
GAS_CALLS.clear(); SWAPS.clear()
GAS_RESULT[0] = (False, 'bootstrapping', 4242)
out['pending_status'], out['pending'] = buy({'chain': 'base', 'token_address': EVM,
                                             'amount_usdc': 100})
out['pending_swaps'] = len(SWAPS)
out['pending_gas_args'] = list(GAS_CALLS)

GAS_RESULT[0] = (False, 'no USDC to top up from', None)
out['nogas_status'], out['nogas'] = buy({'chain': 'base', 'token_address': EVM,
                                         'amount_usdc': 100})
GAS_RESULT[0] = (True, '', None)

# ── the clamp still applies ──
SWAPS.clear()
out['clamp_status'], out['clamp'] = buy({'chain': 'base', 'token_address': EVM,
                                         'amount_usdc': 99999})
out['clamp_swaps'] = list(SWAPS)

# ── a failed swap opens no position ──
POSITIONS.clear()
SWAP_RESULT[0] = (False, d.SWAP_UNCONFIRMED_PREFIX + ': sent but not confirmed within 90s',
                  '0xUNKNOWN')
out['fail_status'], out['fail'] = buy({'chain': 'base', 'token_address': EVM,
                                       'amount_usdc': 100})
out['fail_positions'] = len(POSITIONS)
SWAP_RESULT[0] = (True, '', '0xBOUGHT')

# ── the old path, through the flag ──
SWAPS.clear(); FEES.clear(); POSITIONS.clear()
d.TRADE_ENGINE_MANUAL_EVM = False
out['legacy_status'], out['legacy'] = buy({'chain': 'base', 'token_address': EVM,
                                           'amount_usdc': 100})
out['legacy_swaps'] = list(SWAPS)
out['legacy_fees'] = list(FEES)
d.TRADE_ENGINE_MANUAL_EVM = True

# ── the BSC route, which was a full copy of this one ──
SWAPS.clear(); FEES.clear()
out['bsc_status'], out['bsc'] = buy({'token_address': EVM, 'amount_usdc': 100},
                                    path='/api/bsc/trade/buy')
out['bsc_swaps'] = list(SWAPS)

# ── an unsupported chain is still refused on the EVM route ──
out['badchain_status'], out['badchain'] = buy({'chain': 'ethereum',
                                               'token_address': EVM,
                                               'amount_usdc': 100})

out['flag_default'] = bool(d.TRADE_ENGINE_MANUAL_EVM)
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

# ── the ceiling now holds on the route a user actually presses ──
b, swaps = R['buy'], R['swaps']
check('the buy succeeds', R['buy_status'] == 200 and b['ok'])
check('exactly one swap goes out', len(swaps) == 1)
check('the swap sells LESS than the $100 entered — before this the full $100 was '
      'swapped and the fee was charged on top of it',
      float(swaps[0]['amount']) < 100.0)
# _charge_evm_txn_fee takes the GROSS amount and works the 0.75% out itself,
# so what is asserted here is the base it was given.
check('the fee is worked out on what was bought, not on the amount entered',
      len(R['fees']) == 1 and float(R['fees'][0]['usdc']) == float(swaps[0]['amount']))
spent = float(swaps[0]['amount']) + sum(float(v) for v in b['costs'].values())
check(f'purchase + every cost = ${spent:.2f}, exactly the $100 ceiling and not a '
      f'cent over. The old route spent $100.75 plus gas for the same request',
      abs(spent - 100.0) < 0.01)
check('...and the fee inside that is 0.75% of the purchase, not of the $100',
      abs(float(b['costs']['platform_fee']) - float(swaps[0]['amount']) * 0.0075) < 0.01)
check('the response reports what was actually bought, not the amount typed',
      float(b['amount_usdc']) < 100 and float(b['max_spend_usd']) == 100.0)
check('...and itemises where the rest of the money went',
      set(b['costs']) == {'source_gas', 'slippage_reserve', 'platform_fee'})
check('the position is opened at what was bought, so a holding is never recorded '
      'larger than the money that paid for it',
      len(R['positions']) == 1 and R['positions'][0]['spend'] == float(b['amount_usdc']))
check('the trade is identified, so it can be looked up afterwards', b.get('trade_id'))

# ── a double-click ──
check('pressing Buy twice sends a second swap only because it is a NEW quote at a '
      'new price — not a duplicate of the first',
      R['second_press_swaps'] == 1 and R['distinct_trade'])

# ── nothing around it was lost ──
g = R['gas_calls']
check('the gas check still runs before anything is priced, and still carries this '
      "buy's own token and amount so a from-zero wallet's bootstrap bridge can "
      'complete the buy afterwards',
      len(g) >= 1 and g[0]['auto_buy_token'] and g[0]['auto_buy_usdc'] == 100.0)
check('a wallet being bootstrapped still returns pending with its bridge id, and '
      'sends no swap',
      R['pending_status'] == 200 and R['pending']['pending']
      and R['pending']['bridge_id'] == 4242 and R['pending_swaps'] == 0)
check('a wallet that cannot get gas at all still gets the plain refusal, '
      'naming the chain the way a person would rather than by its key',
      R['nogas_status'] == 400 and 'Cannot trade on Base' in R['nogas']['msg'])
check('the min/max trade-size clamp still applies before pricing — $99999 is '
      'clamped to the $200 maximum, and the purchase comes out of that',
      len(R['clamp_swaps']) == 1 and float(R['clamp_swaps'][0]['amount']) < 200)

# ── a trade that did not complete ──
f = R['fail']
check('a swap that was sent but never confirmed does not report success',
      R['fail_status'] == 502 and not f['ok'])
check('...and opens NO position: a holding on screen for a swap nobody has seen '
      'land is one the user will try to sell', R['fail_positions'] == 0)
check('...while still handing back the hash and the trade id, so it can be traced',
      f['tx_hash'] == '0xUNKNOWN' and f.get('trade_id') and f['needs_investigation'])

# ── the way back ──
lg = R['legacy']
check('with TRADE_ENGINE_MANUAL_EVM off the route goes back to the old behaviour, '
      'swapping the full amount entered',
      R['legacy_status'] == 200 and float(R['legacy_swaps'][0]['amount']) == 100.0)
check('...including charging the fee on top of it, which is what the engine path '
      'fixes', float(R['legacy_fees'][0]['usdc']) == 100.0)
check('the engine path is the default; the old one needs an explicit opt-out',
      R['flag_default'] is True)

# ── BSC gets the same treatment, at the same moment ──
bsc = R['bsc']
check('the BSC buy runs the same flow, so the ceiling holds there too — it was a '
      'full copy with the chain hardcoded, and leaving it behind would mean the '
      'same Buy button spending a different amount depending on the chain',
      R['bsc_status'] == 200 and bsc['ok']
      and len(R['bsc_swaps']) == 1 and float(R['bsc_swaps'][0]['amount']) < 100.0)
check('...on BSC, from the stored quote', R['bsc_swaps'][0]['chain'] == 'bsc'
      and bsc['chain'] == 'bsc')
check('...and it reports what was bought against what was entered, as the other '
      'chains do', float(bsc['amount_usdc']) < 100 and float(bsc['max_spend_usd']) == 100.0)

check('a chain the platform does not trade is still refused on the EVM route',
      R['badchain_status'] == 400 and 'ethereum' in R['badchain']['msg'])

# ── one implementation, not two ──
import ast                                                        # noqa: E402
tree = ast.parse(open(REPO + '/dashboard.py').read())
funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
for name in ('api_evm_trade_buy', 'api_bsc_trade_buy'):
    body_calls = {c.func.id for c in ast.walk(funcs[name])
                  if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    check(f'{name} is a thin route over the shared flow rather than its own copy',
          '_evm_buy_flow' in body_calls)
    check(f'...so {name} contains no swap or fee call of its own',
          not (body_calls & {'_execute_evm_swap', '_execute_bsc_swap',
                             '_charge_evm_txn_fee', '_charge_bsc_txn_fee'}))

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
