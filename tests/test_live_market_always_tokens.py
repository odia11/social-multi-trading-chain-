"""Live Market always shows DexScreener tokens from a $15K market cap.

Live Market showed "No tokens match these filters" with no filter set:
- a refresh where DexScreener calls failed (a timeout, a 429) returned an
  empty list, and that empty list was served as the market;
- that refresh ran inside the visitor's own request, so opening the page
  could wait on DexScreener for many seconds;
- the discovery surfaces alone are small and mostly brand-new micro caps, and
  with a $30K floor only a handful of tokens (11 at one point) were left.

Now the floor is $15K, more DexScreener searches feed the pool, a token seen
in the last five minutes stays listed through a failed refresh, and a
visitor gets the list from a moment ago at once while it refreshes in the
background.

dashboard.py cannot be imported in a test (it starts threads at import), so
the real functions are taken from its source, as in test_market_scanner_filter.
"""
import ast, os, threading, time

SRC = open(os.path.join(os.path.dirname(__file__), '..', 'dashboard.py'), encoding='utf-8').read()
TREE = ast.parse(SRC)
FUNCS = {'_is_market_major_or_impersonator', '_dexscreener_solana_discovery_addresses', '_get_scanner_candidates',
         '_get_scanner_cached', '_refresh_scanner_cached', '_scanner_carry_over'}
CONSTS = {'_MARKET_MAJOR_ADDRESSES', '_MARKET_MAJOR_SYMBOLS', '_MARKET_LIVE_CHAINS', '_SCANNER_SEARCHES',
          '_SCANNER_CARRY_SECONDS', '_LIVE_MARKET_MIN_MCAP_USD'}
found = {}
for node in TREE.body:
    if isinstance(node, ast.FunctionDef) and node.name in FUNCS:
        found[node.name] = ast.get_source_segment(SRC, node)
    elif isinstance(node, (ast.Assign, ast.AnnAssign)):
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target
        if isinstance(target, ast.Name) and target.id in CONSTS:
            found[target.id] = ast.get_source_segment(SRC, node)
missing = (FUNCS | CONSTS) - set(found)
assert not missing, 'missing in dashboard.py: %s' % sorted(missing)

checks = []
def check(name, cond, detail=''):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name + ((' -- ' + detail) if detail and not cond else ''), flush=True)


class Clock:
    """time.time() the test can move forward; everything else is real time."""
    offset = 0.0
    def time(self):
        return time.time() + self.offset
    def sleep(self, s):
        time.sleep(s)
clock = Clock()


class Resp:
    status_code = 200
    def __init__(self, payload):
        self._p = payload
    def json(self):
        return self._p


def pair(sym, addr, mcap, vol=50_000):
    return {'chainId': 'solana', 'dexId': 'raydium', 'pairAddress': 'P' + addr,
            'baseToken': {'address': addr, 'symbol': sym, 'name': sym},
            'priceUsd': '0.01', 'marketCap': mcap, 'liquidity': {'usd': 20_000}, 'volume': {'h24': vol},
            'txns': {'h24': {'buys': 10, 'sells': 5}}, 'priceChange': {'h24': 3}}

MINTS = {'SMALL': 'Mint14k' + 'a' * 30, 'EDGE': 'Mint16k' + 'b' * 30, 'BIG': 'Mint2m' + 'c' * 31, 'SEARCHED': 'MintSrch' + 'd' * 29}
MODE = {'up': True, 'delay': 0.0, 'urls': []}
def fake_dex_get(url, timeout=10, ttl_override=None):
    MODE['urls'].append(url)
    if MODE['delay']:
        time.sleep(MODE['delay'])
    if not MODE['up']:
        return None
    if 'token-boosts/top' in url:
        return Resp([{'chainId': 'solana', 'tokenAddress': MINTS[k]} for k in ('SMALL', 'EDGE', 'BIG')])
    if 'tokens/v1/solana/' in url:
        return Resp([pair('SMALL', MINTS['SMALL'], 14_000), pair('EDGE', MINTS['EDGE'], 16_000), pair('BIG', MINTS['BIG'], 2_000_000)])
    if 'search?q=SOL' in url and 'q=SOLANA' not in url.upper().replace('Q=SOL&', ''):
        return Resp({'pairs': [pair('SEARCHED', MINTS['SEARCHED'], 50_000)]})
    return Resp([])


ns = {'time': clock, 'threading': threading, '_dex_get': fake_dex_get,
      '_DEX_SOLANA_DISCOVERY_META_LOCK': threading.Lock(), '_DEX_SOLANA_DISCOVERY_META': {},
      '_store_observed_market_prices': lambda *a, **k: None,
      '_scanner_cache': {'ts': 0.0, 'data': []}, '_scanner_lock': threading.Lock(),
      '_scanner_refresh_lock': threading.Lock(), '_scanner_seen': {}}
for name in ('_MARKET_LIVE_CHAINS', '_MARKET_MAJOR_ADDRESSES', '_MARKET_MAJOR_SYMBOLS', '_SCANNER_SEARCHES',
             '_SCANNER_CARRY_SECONDS', '_LIVE_MARKET_MIN_MCAP_USD'):
    exec(found[name], ns)
for name in FUNCS:
    exec(found[name], ns)

# 1. what is listed
data = ns['_get_scanner_cached']()
syms = {t['symbol'] for t in data}
check('the floor is $15K', ns['_LIVE_MARKET_MIN_MCAP_USD'] == 15_000)
check('a $16K token is listed, a $14K one is not', 'EDGE' in syms and 'SMALL' not in syms, str(syms))
check('more DexScreener searches feed the list (a token only a search returns is there)',
      'SEARCHED' in syms and sum('latest/dex/search?q=' in u for u in MODE['urls']) >= 5, str(syms))

# 2. DexScreener fails: the market does not go empty
MODE['up'] = False
clock.offset += 20
ns['_scanner_cache']['ts'] = 0.0   # force a real refresh
data = ns['_refresh_scanner_cached']()
check('a refresh where every DexScreener call fails still lists what was seen moments ago',
      {t['symbol'] for t in data} == {'EDGE', 'BIG', 'SEARCHED'}, str([t['symbol'] for t in data]))
clock.offset += ns['_SCANNER_CARRY_SECONDS'] + 5
ns['_scanner_cache']['ts'] = 0.0
data = ns['_refresh_scanner_cached']()
check('...but a token not seen for over five minutes is dropped', data == [], str(data))

# 3. nobody waits on DexScreener
MODE['up'] = True
ns['_scanner_cache']['ts'] = 0.0
ns['_get_scanner_cached']()                      # fill it again
clock.offset += 20                               # now stale
MODE['delay'] = 0.4                              # DexScreener is slow: a full refresh takes ~5s
before = ns['_scanner_cache']['ts']
t0 = time.time()
data = ns['_get_scanner_cached']()
took = time.time() - t0
check('opening Live Market with a stale list answers at once (%.2fs), with the list from a moment ago' % took,
      took < 0.5 and {t['symbol'] for t in data} == {'EDGE', 'BIG', 'SEARCHED'})
deadline = time.time() + 20
while ns['_scanner_cache']['ts'] == before and time.time() < deadline:
    time.sleep(0.2)
time.sleep(0.3)
check('...and the list is refreshed in the background', ns['_scanner_cache']['ts'] > before)
check('...one refresh at a time', not ns['_scanner_refresh_lock'].locked())

print('%d/%d' % (sum(checks), len(checks)))
raise SystemExit(0 if all(checks) else 1)
