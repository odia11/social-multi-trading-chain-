"""POST /api/trade/execute and GET /api/trade/status/<id> — the real routes.

The engine's rules are proved in tests/test_trade_engine_execute.py. What
this file is for is the wiring, and specifically the parts of the wiring that
would be expensive to get wrong:

  a quote id is a bearer token for someone's money, so it is checked against
  the authenticated user rather than trusted;

  the amount comes from the STORED quote, so a client that sends a bigger
  number with a valid quote id gets the quoted number anyway;

  the swap that goes out sells the purchase, not the ceiling -- the single
  difference between this path and the eight legacy ones;

  and the fee is charged on the purchase, not on the amount the user typed.

dashboard.py is imported for real with a throwaway database, so a route
registered wrongly fails here rather than in production.
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

WALLET = 'WALLET1'
EVM = '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
conn = sqlite3.connect(d.DB_FILE)
# Created through the app's own path, then given a trading wallet: an
# INSERT OR IGNORE here silently does nothing if the table has a NOT NULL
# column, and the test would then be exercising a user that does not exist.
uid = d._get_uid(conn, WALLET)
other_uid = d._get_uid(conn, 'OTHER')
conn.execute("UPDATE users SET bsc_wallet_address=?, encrypted_private_key_bsc='ENCRYPTED' "
             "WHERE wallet_address IN (?, 'OTHER')", (EVM, WALLET))
conn.commit()
assert uid and other_uid and uid != other_uid, (uid, other_uid)
conn.close()

# ── everything that touches a chain, replaced ──
d._authenticated_wallet = lambda: WALLET
d._te_gas_usd = lambda chain: Decimal('0.35')
d._te_needs_sponsored_gas = lambda chain, addr: True
d.get_evm_usdc_balance = lambda addr, chain='bsc': 500.0
d.get_token_data = lambda a: {'symbol': 'PEPE', 'price': 0.01}
d._ensure_evm_gas = lambda *a, **k: (True, '', None)

def fake_0x(sell, buy, amount, taker, chain):
    return {'buyAmount': '1000000000000000000', 'minBuyAmount': '985000000000000000',
            'transaction': {'gas': '200000', 'gasPrice': '10000000'}}
d._te_swap_provider = lambda chain: d.ZeroExProvider(fake_0x)

SWAPS, FEES = [], []
class FakeKey:
    def __enter__(self): return 'PRIVATE-KEY'
    def __exit__(self, *a): return False
d._use_key = lambda blob, wallet: FakeKey()

SWAP_RESULT = [(True, '', '0xSWAPPED')]
def fake_swap(wallet, pk, action, token, amount_str, chain='bsc'):
    SWAPS.append({'action': action, 'token': token, 'amount': amount_str, 'chain': chain})
    return SWAP_RESULT[0]
d._execute_evm_swap = fake_swap

def fake_fee(pk, wallet, user_id, symbol, usdc_amount, kind, chain='bsc', **kw):
    FEES.append({'symbol': symbol, 'usdc': usdc_amount, 'kind': kind, 'chain': chain})
d._charge_evm_txn_fee = fake_fee

def quote(body=None):
    r = c.post('/api/trade/quote', json=body or {'chain': 'base',
                                                 'token_address': '0xTOKEN',
                                                 'max_spend_usd': '100'})
    return r.get_json()

def execute(body):
    # The route's own limit is 10/min, which is right for real money and wrong
    # for a test that exercises a dozen outcomes. Cleared per call rather than
    # loosened in the app, so the production limit stays exactly as shipped.
    with d._rl_lock:
        d._rl_hits.clear()
    r = c.post('/api/trade/execute', json=body)
    return r.status_code, r.get_json()

# ── anon ──
d._authenticated_wallet = lambda: None
out['anon_exec'] = c.post('/api/trade/execute', json={'quote_id': 'x'}).status_code
out['anon_status'] = c.get('/api/trade/status/x').status_code
d._authenticated_wallet = lambda: WALLET

# ── the happy path ──
q = quote()
out['quote'] = q
out['exec_status'], out['exec'] = execute({'quote_id': q['quote_id']})
out['swaps'] = list(SWAPS)
out['fees'] = list(FEES)

# ── status ──
r = c.get('/api/trade/status/' + out['exec']['trade_id'])
out['status_code'], out['status'] = r.status_code, r.get_json()

# ── a retry sends nothing more ──
n_before = len(SWAPS)
out['retry_status'], out['retry'] = execute({'quote_id': q['quote_id']})
out['swaps_after_retry'] = len(SWAPS) - n_before

# ── a client that sends its own amount is ignored ──
SWAPS.clear()
q2 = quote()
execute({'quote_id': q2['quote_id'], 'max_spend_usd': '100000',
         'amount_usdc': 99999, 'token_address': '0xEVIL', 'chain': 'polygon'})
out['forged'] = list(SWAPS)

# ── someone else's quote ──
q3 = quote()
d._authenticated_wallet = lambda: 'OTHER'
SWAPS.clear()
out['steal_status'], out['steal'] = execute({'quote_id': q3['quote_id']})
out['steal_swaps'] = len(SWAPS)
out['steal_view'] = c.get('/api/trade/status/' + out['exec']['trade_id']).status_code
d._authenticated_wallet = lambda: WALLET

# ── an unknown quote, and one that is not executable ──
out['unknown_status'], out['unknown'] = execute({'quote_id': 'deadbeef'})
out['noquote_status'], _ = execute({})

# ── a swap that reverts ──
SWAP_RESULT[0] = (False, d.SWAP_REVERTED_MSG, '0xREVERTED')
q4 = quote()
out['revert_status'], out['revert'] = execute({'quote_id': q4['quote_id'],
                                               'idempotency_key': 'rv'})

# ── a swap that was sent but never confirmed ──
SWAP_RESULT[0] = (False, d.SWAP_UNCONFIRMED_PREFIX + ': sent but not confirmed within 90s',
                  '0xUNKNOWN')
q5 = quote()
out['unconf_status'], out['unconf'] = execute({'quote_id': q5['quote_id'],
                                               'idempotency_key': 'uc'})

# ── a swap that never went out ──
SWAP_RESULT[0] = (False, 'Insufficient BNB for gas fees', '')
q6 = quote()
out['nosend_status'], out['nosend'] = execute({'quote_id': q6['quote_id'],
                                               'idempotency_key': 'ns'})
SWAP_RESULT[0] = (True, '', '0xSWAPPED')

# ── not enough balance ──
d.get_evm_usdc_balance = lambda addr, chain='bsc': 3.0
q7 = quote()
SWAPS.clear()
out['poor_status'], out['poor'] = execute({'quote_id': q7['quote_id'],
                                           'idempotency_key': 'pr'})
out['poor_swaps'] = len(SWAPS)
d.get_evm_usdc_balance = lambda addr, chain='bsc': 500.0

# ── a chain the engine does not execute yet ──
# Quoting Solana needs a live SOL price, which this sandbox has no route to,
# so the stored quote's chain is rewritten instead. The guard being tested is
# the endpoint's, and it reads exactly this column.
q8 = quote()
conn = sqlite3.connect(d.DB_FILE)
conn.execute("UPDATE trade_quotes SET destination_chain='solana' WHERE quote_id=?",
             (q8['quote_id'],))
conn.commit(); conn.close()
SWAPS.clear()
out['solana_status'], out['solana'] = execute({'quote_id': q8['quote_id']})
out['solana_swaps'] = len(SWAPS)

out['routes'] = sorted(str(r.rule) for r in d.app.url_map.iter_rules()
                       if str(r.rule).startswith('/api/trade/'))
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

# ── the routes ──
check('both routes are registered',
      '/api/trade/execute' in R['routes'] and '/api/trade/status/<trade_id>' in R['routes'])
check('an unauthenticated caller cannot execute or inspect a trade',
      R['anon_exec'] == 401 and R['anon_status'] == 401)

# ── RULE 1, through the real route ──
q, ex, swaps = R['quote'], R['exec'], R['swaps']
check('the trade completes', R['exec_status'] == 200 and ex['ok'] and ex['completed'])
check('exactly one swap went out', len(swaps) == 1)
check('the swap SELLS THE PURCHASE, not the $100 the user entered — this single '
      'number is the difference between the engine and every legacy endpoint',
      swaps[0]['amount'] == q['token_purchase_usd'] and float(swaps[0]['amount']) < 100)
check('...on the chain and token from the stored quote',
      swaps[0]['chain'] == 'base' and swaps[0]['token'] == '0xTOKEN'
      and swaps[0]['action'] == 'buy')
check('the fee is charged on the PURCHASE too. The legacy path charges 0.75% of '
      'the full amount the user typed, on top of having already swapped all of '
      'it — so the real spend exceeds the number on screen',
      len(R['fees']) == 1 and str(R['fees'][0]['usdc']) == str(float(q['token_purchase_usd'])))
check('purchase plus fee never exceeds what the user agreed to spend',
      float(q['token_purchase_usd']) + float(q['costs_by_kind']['platform_fee']) <= 100.0)
check('the transaction hash comes back', ex['tx_hash'] == '0xSWAPPED')

# ── status ──
st = R['status']
check('the status route reports the finished trade',
      R['status_code'] == 200 and st['completed'] and st['finished'])
check('...with what it actually cost against what was quoted, per cost kind',
      'platform_fee' in st['costs'] and 'quoted' in st['costs']['platform_fee'])
check('...and the slippage reserve shows as quoted but never spent',
      st['costs']['slippage_reserve']['quoted'] > 0
      and st['costs']['slippage_reserve']['actual'] == 0)

# ── RULE 2, through the real route ──
check('pressing Buy twice on one quote does NOT send a second swap',
      R['swaps_after_retry'] == 0)
check('...and the second press returns the same trade rather than an error',
      R['retry']['trade_id'] == ex['trade_id'] and R['retry_status'] == 200)

# ── the client cannot choose the numbers ──
f = R['forged']
check('a client that sends its own amount, token and chain alongside a valid '
      'quote id is ignored — every number comes from the stored quote',
      len(f) == 1 and f[0]['token'] == '0xTOKEN' and f[0]['chain'] == 'base'
      and float(f[0]['amount']) < 100)

# ── a quote id is not a bearer token ──
check('another account cannot execute a quote priced for this one',
      R['steal_status'] == 403 and R['steal_swaps'] == 0)
check('...and cannot read its trade either', R['steal_view'] == 404)

check('an unknown quote is refused', R['unknown_status'] == 404)
check('a request with no quote is refused', R['noquote_status'] == 400)

# ── the three on-chain outcomes are told apart ──
rv = R['revert']
check('a swap that reverted on-chain is a failure that keeps its hash',
      R['revert_status'] == 200 and not rv['ok'] and rv['tx_hash'] == '0xREVERTED')
check('...and is NOT flagged — a revert is resolved, the purchase simply did not '
      'happen', not rv['needs_investigation'])

uc = R['unconf']
check('a swap that was sent but never confirmed is not a completed trade',
      not uc['ok'] and not uc['completed'])
check('...it keeps the hash, so the transaction can still be found',
      uc['tx_hash'] == '0xUNKNOWN')
check('...and IS flagged, because the money may be gone. The legacy path cannot '
      'even reach this case: before the fix it threw the hash away on a receipt '
      'timeout and reported it as if nothing had been sent',
      uc['needs_investigation'])

ns = R['nosend']
check('a swap that never went out fails with the real reason and no hash',
      not ns['ok'] and ns['tx_hash'] == '' and 'BNB' in ns['msg'])
check('...and is not flagged, because nothing is unresolved',
      not ns['needs_investigation'])

# ── the balance is read server-side ──
check('a trade larger than the wallet balance is refused before any swap is sent',
      R['poor_status'] == 200 and not R['poor']['ok'] and R['poor_swaps'] == 0)
check('...naming the real balance, which was read on the server and not taken '
      'from the request', '$3' in R['poor']['msg'])

# ── chains the engine does not cover yet ──
check('a chain the engine does not cover is refused outright rather than quietly '
      'falling back to a legacy path whose guarantees are the ones being '
      'replaced',
      R['solana_status'] == 400 and 'does not execute solana' in R['solana']['msg']
      and R['solana_swaps'] == 0)

# ── the legacy paths are untouched ──
import ast                                                        # noqa: E402
src = open(REPO + '/dashboard.py').read()
tree = ast.parse(src)
legacy = {'api_evm_trade_buy', 'api_bsc_trade_buy', 'api_instant_trade',
          'api_manual_buy', 'api_pump_scanner_buy'}
touched = []
for n in ast.walk(tree):
    if isinstance(n, ast.FunctionDef) and n.name in legacy:
        for sub in ast.walk(n):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr in ('execute_trade', 'save_quote')):
                touched.append(n.name)
check('no legacy execution endpoint has been rewired yet — they are moved one at '
      'a time, so a mistake in the engine cannot take out a working trade path',
      not touched)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
