"""The bot sees new tokens sooner, and may buy heavily-traded trending tokens.

- Discovery read up to 100 tokens one by one, 0.3 s apart, then slept 30 s:
  a new candidate could take a minute to reach the bot. Tokens are now read
  30 per DexScreener request and the shared list refreshes every 10 s.
- "+50% in 1h = momentum exhausted" kept the bot out of exactly the trending
  runners people expect it to catch. A token on DexScreener's trending list
  with heavy volume may now be bought after a big hour; every other entry
  rule and safety check still applies.
"""
import os, sys, tempfile
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_POSITION_GUARDIAN': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

def pair(mint, liq, price='0.01', vol1h=50_000):
    return {'chainId': 'solana', 'baseToken': {'address': mint, 'symbol': mint[:4]}, 'priceUsd': price,
            'liquidity': {'usd': liq}, 'volume': {'m5': 9000, 'h1': vol1h, 'h24': 400_000},
            'priceChange': {'m5': 4, 'h1': 60}, 'txns': {'h24': {'buys': 300, 'sells': 120}},
            'pairAddress': 'P' + mint, 'dexId': 'raydium'}

mints = ['M%02d' % i for i in range(65)]
calls = []
class R:
    status_code = 200
    def __init__(self, body): self._b = body
    def json(self): return self._b
def fake_dex(url, timeout=10, ttl_override=None):
    calls.append((url, ttl_override))
    asked = url.rsplit('/', 1)[1].split(',')
    pairs = []
    for m in asked:
        pairs += [pair(m, 5_000, '0.02'), pair(m, 90_000, '0.01')]   # deepest pool must win
    return R({'pairs': pairs})
real = d._dex_get
d._dex_get = fake_dex
got = d._token_data_batch(mints)
d._dex_get = real
check('65 tokens are read in 3 requests (30 per request), not 65',
      len(calls) == 3 and all(len(u.rsplit('/', 1)[1].split(',')) <= 30 for u, _ in calls) and len(got) == 65)
check('...each from its deepest pool, exactly as the single-token read does',
      got['M07']['liquidity'] == 90_000 and got['M07']['price'] == 0.01)
check('...and fresh every round (not the 30 s cache)', all(t is not None and t <= 9 for _, t in calls))

calls.clear()
def failing(url, timeout=10, ttl_override=None):
    calls.append(url); return None
d._dex_get = failing
single = []
real_single = d.get_token_data
d.get_token_data = lambda m, chain=None, **k: single.append(m) or {'price': 1.0}
real_sleep = d.time.sleep; d.time.sleep = lambda s: None
got = d._token_data_batch(mints[:5])
d.get_token_data = real_single; d._dex_get = real; d.time.sleep = real_sleep
check('a batch that fails falls back to reading its tokens one by one -- nothing skipped silently',
      single == mints[:5] and len(got) == 5)

src = open(os.path.join(ROOT, 'dashboard.py'), encoding='utf-8').read()
loop = src[src.index('def token_loop():'):src.index('# ── TRADE RECORDING ──')]
check('discovery uses the batch and refreshes every 10 s',
      "_batch = _token_data_batch(mints, chain='solana')" in loop and 'time.sleep(DISCOVERY_INTERVAL)' in loop
      and 'DISCOVERY_INTERVAL = 10 ' in src and 'time.sleep(0.3)  # stagger per-token calls' not in loop)

hot = {'trending': True, 'volume1h': 300_000, 'volume24h': 1_000_000}
check('a trending token with heavy volume may be bought after a big hour',
      d._trending_high_volume(hot) and d._trending_high_volume({**hot, 'volume1h': 10_000, 'volume24h': 2_500_000}))
check('...not when it is not trending, or trades thinly',
      not d._trending_high_volume({**hot, 'trending': False})
      and not d._trending_high_volume({**hot, 'volume1h': 10_000, 'volume24h': 100_000})
      and not d._trending_high_volume({}))
check('the +50%/1h rule applies to everything else',
      "if _t.get('change1h', 0) >= 50 and not _trending_high_volume(_t):" in src
      and "'trending':      mint in _trending_mints," in loop and '_trending_mints.update(_trend)' in src)
raise SystemExit(0 if all(checks) else 1)
