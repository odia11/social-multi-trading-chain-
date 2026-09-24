"""A Live Market chart must plot the card's own token, not the other side of
its pool. GeckoTerminal's `token=base` is GeckoTerminal's idea of the base
token, which doesn't always match DexScreener's (where the card's mint, header
price and live ticks come from): a $0.001979 token on Robinhood Chain was drawn
as a $773 line. The chart now asks GeckoTerminal for the token by address."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('ENCRYPTION_KEY', '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=')
import app_entry
d = app_entry._dashboard
app = app_entry.app

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

MINT = '0xcd00000000000000000000000000000000aa93c0'
PAIR = '0x1111111111111111111111111111111111111111'
OTHER = '0x2222222222222222222222222222222222222222'
urls = []

class R:
    def __init__(self, body): self.status_code = 200; self._b = body
    def json(self): return self._b

def fake_get(url, *a, **k):
    urls.append(url)
    if '/ohlcv/' in url:
        # GeckoTerminal answers for whichever side it was asked for.
        px = 0.001979 if ('token=' + MINT.lower()) in url else 773.32
        return R({'data': {'attributes': {'ohlcv_list': [
            [1700000000 + i * 300, px, px, px, px, 10] for i in range(20)]}}})
    if url.rstrip('/').endswith('/pools/' + PAIR):
        # GeckoTerminal's base is the OTHER token; ours is its quote.
        return R({'data': {'attributes': {'base_token_price_usd': '773.32',
                                          'quote_token_price_usd': '0.001979'},
                           'relationships': {
                               'base_token': {'data': {'id': 'robinhood_' + OTHER}},
                               'quote_token': {'data': {'id': 'robinhood_' + MINT.lower()}}}}})
    raise AssertionError('unexpected upstream call: ' + url)

d.requests.get = fake_get
d._best_stored_market_candles = lambda chain, pair, tf, limit=60: ([], tf)
with d._chart_cache_lock: d._chart_cache.clear()
with d._gt_budget_lock: d._gt_budget['tokens'] = 25.0; d._gt_budget['at'] = time.time()

with app.test_client() as c:
    j = c.get(f'/api/chart/{MINT}?tf=5m&pair={PAIR}&chain=robinhood').get_json()
ohlcv = [u for u in urls if '/ohlcv/' in u]
check('OHLCV is requested for the token address, not token=base',
      ohlcv and ('token=' + MINT.lower()) in ohlcv[0] and 'token=base' not in ohlcv[0])
check('the chart plots the token\'s own price', j['candles'] and abs(j['candles'][-1]['c'] - 0.001979) < 1e-9)

# The no-history fallback reads the same side of the pool.
with d._chart_cache_lock: d._chart_cache.clear()
d._gt_fetch_ohlcv = lambda *a, **k: []
urls.clear()
with app.test_client() as c:
    j = c.get(f'/api/chart/{MINT}?tf=5m&pair={PAIR}&chain=robinhood').get_json()
check('current price falls back to the token\'s side of the pool', abs((j.get('current_price') or 0) - 0.001979) < 1e-9)

check('Solana mints keep their case', d._gt_token_param('solana', 'AbCdEf') == 'AbCdEf')
check('unknown mint still means base', d._gt_token_param('solana', '') == 'base')

# Browser guard: candles 10x+ away from the card's price are not drawn.
js = open(os.path.join(os.path.dirname(__file__), '..', 'static', 'live-market-pro.js')).read()
check('client refuses candles 10x away from the token price',
      'function _candlesMatchPrice(' in js and '!_candlesMatchPrice(r.candles, ref)' in js
      and '!_candlesMatchPrice(cached.c, st.seedPrice)' in js)

raise SystemExit(0 if all(checks) else 1)
