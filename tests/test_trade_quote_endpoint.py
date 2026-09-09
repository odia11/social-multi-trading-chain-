"""POST /api/trade/quote — the real route, driven through Flask's test client.

The engine's own arithmetic is covered elsewhere. What matters here is the
wiring: does the endpoint refuse an unauthenticated caller, does it convert
a JSON number into something the cost engine will accept, does a provider
outage come back as an un-executable quote rather than a 500, and — the one
that would be expensive to get wrong — does it stay read-only.

dashboard.py is imported for real, with a throwaway database, so a mistake
in how the route is registered fails here rather than in production.
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


# The app starts background threads on import, so it runs in a subprocess
# that exits when the checks are done.
PROBE = r'''
import json, sys
from decimal import Decimal
import dashboard as d

out = {}
d.app.config['TESTING'] = True
c = d.app.test_client()

# ── unauthenticated ──
r = c.post('/api/trade/quote', json={'chain': 'base', 'token_address': '0x1',
                                     'max_spend_usd': '100'})
out['anon_status'] = r.status_code

# ── authenticated, with every outside call replaced ──
d._authenticated_wallet = lambda: 'WALLET1'
d._get_uid = lambda conn, w: 1
d._te_gas_usd = lambda chain: Decimal('0.35')
d._te_needs_sponsored_gas = lambda chain, addr: True

conn = __import__('sqlite3').connect(d.DB_FILE)
conn.execute("INSERT OR IGNORE INTO users (wallet_address, bsc_wallet_address) "
             "VALUES ('WALLET1','0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')")
conn.commit(); conn.close()

def fake_0x(sell, buy, amount, taker, chain):
    return {'buyAmount': '1000000000000000000', 'minBuyAmount': '990000000000000000',
            'transaction': {'gas': '200000', 'gasPrice': '10000000'}}
d._get_0x_quote = fake_0x
d._te_swap_provider = lambda chain: d.ZeroExProvider(fake_0x)

def post(body):
    r = c.post('/api/trade/quote', json=body)
    try:
        return r.status_code, r.get_json()
    except Exception:
        return r.status_code, None

out['ok_status'], out['ok'] = post({'chain': 'base', 'token_address': '0x1',
                                    'max_spend_usd': '100'})
# a JSON number, not a string -- the shape a browser actually sends
out['num_status'], out['num'] = post({'chain': 'base', 'token_address': '0x1',
                                      'max_spend_usd': 100})
out['zero_status'], out['zero'] = post({'chain': 'base', 'token_address': '0x1',
                                        'max_spend_usd': '0'})
out['badchain_status'], out['badchain'] = post({'chain': 'ethereum',
                                                'token_address': '0x1',
                                                'max_spend_usd': '100'})
out['notoken_status'], out['notoken'] = post({'chain': 'base', 'max_spend_usd': '100'})

# provider outage
def boom(*a, **k):
    raise RuntimeError('0x returned 503')
d._te_swap_provider = lambda chain: d.ZeroExProvider(boom)
out['down_status'], out['down'] = post({'chain': 'base', 'token_address': '0x1',
                                        'max_spend_usd': '100'})

# gas that cannot be priced
d._te_swap_provider = lambda chain: d.ZeroExProvider(fake_0x)
def gas_boom(chain):
    raise RuntimeError('rpc unreachable')
d._te_gas_usd = gas_boom
out['nogas_status'], out['nogas'] = post({'chain': 'base', 'token_address': '0x1',
                                          'max_spend_usd': '100'})

out['routes'] = sorted(str(r.rule) for r in d.app.url_map.iter_rules()
                       if 'trade/quote' in str(r.rule))
out['methods'] = sorted(m for r in d.app.url_map.iter_rules()
                        if str(r.rule) == '/api/trade/quote' for m in r.methods)
print('__RESULT__' + json.dumps(out))
'''

from cryptography.fernet import Fernet
env = dict(os.environ)
env.update({'ENCRYPTION_KEY': Fernet.generate_key().decode(),
            'SECRET_KEY': 'test-only', 'DATA_DIR': tempfile.mkdtemp()})
res = subprocess.run([sys.executable, '-c', PROBE], cwd=REPO, env=env,
                     capture_output=True, text=True, timeout=300)
line = next((l for l in res.stdout.split('\n') if l.startswith('__RESULT__')), None)
if not line:
    print(res.stdout[-3000:]); print(res.stderr[-3000:])
    check('the probe ran at all', False)
    sys.exit(1)
R = json.loads(line[len('__RESULT__'):])

# ── the route exists and is POST-only ──
check('the route is registered', R['routes'] == ['/api/trade/quote'])
check('...as POST — a quote reserves nothing, but it is not a cacheable GET either',
      'POST' in R['methods'] and 'GET' not in R['methods'])

# ── auth ──
check('an unauthenticated caller is refused', R['anon_status'] == 401)

# ── the happy path ──
q = R['ok']
check('an authenticated quote succeeds', R['ok_status'] == 200 and q['ok'])
check('the ceiling holds exactly: total spend equals the amount entered',
      q['total_user_spend_usd'] == '100.00')
check('the purchase is the REMAINDER, not the amount entered',
      q['token_purchase_usd'] != '100' and float(q['token_purchase_usd']) < 100)
check('OrcAgent pays nothing', q['orcagent_subsidy_usd'] == '0')
check('the quote is executable', q['can_execute'])
check('the breakdown names every cost the user pays',
      set(q['costs_by_kind']) == {'source_gas', 'slippage_reserve', 'platform_fee'})
check('sponsored gas is charged to the user, not to OrcAgent',
      [c for c in q['costs'] if c['kind'] == 'source_gas'][0]['payer'] == 'user')
check('...and is still marked as sponsored, so the sponsor can be repaid',
      [c for c in q['costs'] if c['kind'] == 'source_gas'][0]['sponsored'])
check('a same-chain quote names no bridge', q['same_chain'] and 'bridge' not in q['route'])
check('the quote carries an id and an expiry', q['quote_id'] and q['expires_in_seconds'] > 0)
check('timings are reported per stage', 'total_ms' in q['timings_ms'])

check('a JSON number is accepted and priced identically to a string — a browser '
      'sends 100, not "100", and the cost engine refuses floats',
      R['num_status'] == 200 and R['num']['total_user_spend_usd'] == '100.00')

# ── refusals ──
check('an amount of zero is refused', R['zero_status'] == 400)
check('a chain the platform does not trade is refused', R['badchain_status'] == 400)
check('a request with no token is refused', R['notoken_status'] == 400)

check('a provider outage returns a quote that CANNOT execute, with the real '
      'reason — not a 500, and not a route priced at nothing',
      R['down_status'] == 200 and R['down']['can_execute'] is False
      and '503' in R['down']['reject_reason'])
check('gas that cannot be priced also refuses rather than costing zero',
      R['nogas_status'] == 200 and R['nogas']['can_execute'] is False
      and 'gas' in R['nogas']['reject_reason'])

# ── still executes nothing ──
import ast                                                    # noqa: E402
src = open(REPO + '/dashboard.py').read()
tree = ast.parse(src)
fn = next(n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef) and n.name == 'api_trade_quote')
called = {n.func.id for n in ast.walk(fn)
          if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
forbidden = {'_execute_evm_swap', '_execute_user_swap', '_execute_user_swap_ex',
             '_execute_bsc_swap', '_charge_txn_fee', '_charge_evm_txn_fee',
             '_sponsor_evm_gas', '_sponsor_solana_gas', '_ensure_evm_gas'}
check('the quote endpoint calls nothing that executes, charges or sponsors — it '
      'prices a trade and stops there', not (called & forbidden))
# The one thing it does write is the quote it just showed. Execution reads
# that row instead of re-pricing, so the number cannot move between being
# shown and being spent. Asserted by name rather than by "no INSERT appears
# in this function": the INSERT lives in the ledger, so the old spelling of
# this check would have passed no matter what the endpoint stored.
def _calls(name):
    f = next(n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name == name)
    return ({c.func.attr for c in ast.walk(f)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
            | {c.func.id for c in ast.walk(f)
               if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)})

endpoint_calls = _calls('api_trade_quote')
check('the endpoint prices through the shared builder rather than its own copy — '
      'two copies is how one route ends up quoting on different terms from the '
      'one the user was shown',
      '_te_build_and_store_quote' in endpoint_calls)
stores = endpoint_calls | _calls('_te_build_and_store_quote')
check('...and the only thing stored is the quote itself, so execution spends the '
      'number the user was shown rather than a fresh one', 'save_quote' in stores)
check('...it stores nothing else — no trade, no reservation, no cost line',
      not (stores & {'start_execution', 'reserve', 'record_costs', 'settle',
                     'transition', 'execute_trade', 'attach_to_trade'}))

# ── a valuation is not a swap ──────────────────────────────────────────────
# _te_native_price_usd asks "what is one BNB worth in USDC". It used to ask
# that through /quote, which builds a swap FOR somebody and requires a real
# taker -- and the value passed for that taker was the native-token sentinel,
# which is not an address. 0x answered 400 on every chain. It could not be
# caught in development, where 0x is unreachable, so it is pinned here.
native_fn = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == '_te_native_price_usd')
native_src = ast.get_source_segment(src, native_fn) or ''
check('the native-price lookup uses the PRICE endpoint, not the quote endpoint '
      '— it is a valuation, and nobody is swapping anything',
      '_get_0x_price' in native_src and '_get_0x_quote' not in native_src)
check('...so it never has to invent a taker. Passing the native-token sentinel '
      'as an address is what produced a 400 on every chain at once',
      'BNB_NATIVE_ADDR' in native_src and native_src.count('BNB_NATIVE_ADDR') == 1)
price_fn = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == '_get_0x_price')
price_src = ast.get_source_segment(src, price_fn) or ''
check('the price endpoint is called without a taker parameter at all',
      'allowance-holder/price' in price_src and 'taker' not in price_src.split('params=')[1].split(')')[0])

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
