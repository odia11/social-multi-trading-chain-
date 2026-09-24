"""Live Market charts must load like an exchange app: cached history is
answered instantly (fresh or stale), GeckoTerminal's free rate limit is
protected by one shared server-side budget instead of a 2.1s-per-request
browser queue, and the scanner pre-warms the charts it is about to show."""
import os, sys, time, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('ENCRYPTION_KEY', '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=')
import app_entry
d = app_entry._dashboard
app = app_entry.app

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

PAIR = 'Pair1111111111111111111111111111111111111111'
MINT = 'Mint1111111111111111111111111111111111111111'
calls = []
class R:
    status_code = 200
    def json(self):
        return {'data': {'attributes': {'ohlcv_list': [
            [1700000000 + i * 300, 1.0, 1.1, 0.9, 1.0 + i / 100, 10] for i in range(20)]}}}
def fake_get(url, *a, **k):
    if 'geckoterminal' in url:
        calls.append(url); time.sleep(0.6)   # a slow provider
        return R()
    raise AssertionError('unexpected upstream call: ' + url)
d.requests.get = fake_get
d._best_stored_market_candles = lambda chain, pair, tf, limit=60: ([], tf)

def reset(tokens):
    with d._chart_cache_lock: d._chart_cache.clear()
    with d._gt_budget_lock:
        d._gt_budget['tokens'] = float(tokens); d._gt_budget['at'] = time.time()
    calls.clear()

def get_chart():
    t0 = time.time()
    with app.test_client() as c:
        r = c.get(f'/api/chart/{MINT}?tf=5m&pair={PAIR}&chain=solana')
    return r.get_json(), time.time() - t0

def wait_calls(n, timeout=5):
    end = time.time() + timeout
    while len(calls) < n and time.time() < end: time.sleep(0.05)
    return len(calls) >= n

# 1. Cold miss with budget: one synchronous fetch, real candles.
reset(25)
j, dt = get_chart()
check('cold miss fetches once and returns candles', len(calls) == 1 and len(j['candles']) == 20)

# 2. Fresh cache: instant, no upstream call.
calls.clear()
j, dt = get_chart()
check('fresh cache answers without calling GeckoTerminal', not calls and len(j['candles']) == 20)
check('fresh cache answers instantly', dt < 0.3)

# 3. Stale cache: answered instantly with the old candles, refreshed behind it.
with d._chart_cache_lock:
    k = ('solana', PAIR, '5m', MINT); d._chart_cache[k] = (time.time() - d._CHART_CACHE_TTL - 5, d._chart_cache[k][1])
calls.clear()
j, dt = get_chart()
check('stale cache is answered instantly (stale-while-revalidate)', dt < 0.3 and len(j['candles']) == 20)
check('stale cache is refreshed in the background', wait_calls(1))

# 4. Budget spent: never blocks on the provider; background fill instead.
reset(0)
j, dt = get_chart()
check('an exhausted budget answers immediately instead of waiting', dt < 0.3 and calls == [])
with d._gt_budget_lock: d._gt_budget['tokens'] = 5.0
check('...and the cache fills in the background once budget returns', wait_calls(1))
time.sleep(0.8)
j, dt = get_chart()
check('the next request gets the background-filled candles instantly', dt < 0.3 and len(j['candles']) == 20)

# 5. An empty/failed fetch backs off briefly, not for the full 5 minutes.
with d._chart_cache_lock:
    d._chart_cache[('solana', 'EmptyPair', '5m', 'base')] = (time.time() - d._CHART_EMPTY_TTL - 1, [])
_, fresh = d._chart_cache_lookup('solana', 'EmptyPair', '5m')
check('an empty result is retried after _CHART_EMPTY_TTL', fresh is False)

# 6. The scanner pre-warms the charts it is about to show, keeping a reserve.
reset(25)
toks = [{'pair_address': f'Warm{i:040d}', 'chain': 'solana'} for i in range(5)]
d._warm_scanner_charts(toks)
check('scanner warming fetches the listed charts in the background', wait_calls(5, timeout=8))
reset(d._GT_WARM_RESERVE)   # only the reserve left
d._warm_scanner_charts([{'pair_address': 'Reserve' + '0' * 37, 'chain': 'solana'}])
time.sleep(1.5)
check('warming never spends the reserve kept for interactive requests', calls == [])

raise SystemExit(0 if all(checks) else 1)
