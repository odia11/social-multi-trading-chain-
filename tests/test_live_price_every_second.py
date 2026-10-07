"""The Live Market chart price updates every second.

It ticked every 2 s (client poll 2000 ms, server cache 2 s). Now 1 s both,
and the server makes that safe for DexScreener (~300 requests/minute):
- single flight per chain: viewers asking at the same moment share ONE
  upstream read instead of each making their own;
- an upstream budget of 200 reads/minute; past it a viewer gets the last
  known price (a few seconds old) rather than an error;
- the endpoint's rate limit allows a tick per second.
"""
import os, sys, tempfile, threading, time
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(), 'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_POSITION_GUARDIAN': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

js = open(os.path.join(ROOT, 'static', 'live-market-pro.js'), encoding='utf-8').read()
check('the page asks for the chart price every second', 'var _pricePollBaseMs = 1000;' in js)
check('...measured from when the last ask STARTED, on a 250 ms scheduler (it drifted to every ~1.5 s)',
      '_priceNextAt=tickStarted+_pricePollBaseMs;' in js and 'setInterval(tickLivePrices,250)' in js)
check('...and the server keeps a price for one second', d._LIVE_PRICE_TTL == 1)
src = open(os.path.join(ROOT, 'dashboard.py'), encoding='utf-8').read()
check('...with a rate limit that allows a tick per second',
      "@app.route('/api/market/prices-batch')\n@rate_limit(150, 60)" in src)

PAIR = '8sLbNZoA1cfnvMJLPfp98ZLAnFSYCFApfJKMbiXNLwxj'
upstream = []
price = {'v': 1.0}
class R:
    status_code = 200
    def __init__(self, pairs): self._p = pairs
    def json(self): return {'pairs': [{'pairAddress': p, 'priceUsd': str(price['v'])} for p in self._p]}
def fake_dex_get(url, timeout=8, ttl_override=None, **k):
    if '/latest/dex/pairs/' not in url:
        return None
    upstream.append(time.time())
    time.sleep(0.2)
    return R(url.rsplit('/', 1)[1].split(','))
d._dex_get = fake_dex_get
d._store_observed_market_prices = lambda *a, **k: None
d._live_price_cache.clear()

results = []
def viewer():
    results.append(d._market_prices_for_pairs('solana', [PAIR]).get(PAIR.lower()))
threads = [threading.Thread(target=viewer) for _ in range(10)]
for t in threads: t.start()
for t in threads: t.join()
check('ten viewers asking at once share ONE upstream read', len(upstream) == 1 and results == [1.0] * 10)

price['v'] = 1.05
time.sleep(1.05)
got = d._market_prices_for_pairs('solana', [PAIR]).get(PAIR.lower())
check('one second later the next ask sees the new price', got == 1.05 and len(upstream) == 2)

d._live_price_budget['tokens'] = 0.0
d._live_price_budget['at'] = time.time()
price['v'] = 9.99
time.sleep(1.05)
d._live_price_budget['tokens'] = 0.0
d._live_price_budget['at'] = time.time()
got = d._market_prices_for_pairs('solana', [PAIR]).get(PAIR.lower())
check('over the upstream budget: no extra read, the last known price instead of nothing',
      got == 1.05 and len(upstream) == 2)
check('the budget keeps all viewers together under DexScreener\'s limit', d._LIVE_PRICE_UPSTREAM_PER_MIN <= 250)
raise SystemExit(0 if all(checks) else 1)
