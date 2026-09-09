"""Make the Live Market charts actually move.

WHY THEY SAT STILL
Not because the page polled too slowly -- it asked for the chart every five
seconds. The chart is drawn from 5-minute candles, and between two candles
there is genuinely nothing new to draw. Polling harder could not have helped:
the answer only changes every few minutes. The server also caches candles for
30 seconds, so five out of every six of those requests fetched a byte-for-byte
identical reply.

WHAT ACTUALLY MOVES
The price right now. That was fetched only as a fallback for pools too new to
have candles -- never on the normal path, which is exactly the path everyone
is looking at.

DOING IT WITHOUT HAMMERING ANYONE
One request per card per tick would be thirty requests for a screen of thirty
tokens. DexScreener takes up to 30 pair addresses in one call, so the whole
page costs a single upstream request -- fewer than the chart polling it lets
us slow down, not more.
"""
import ast
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/dashboard.py', encoding='utf-8').read()
JS = open(REPO + '/static/live-market-pro.js', encoding='utf-8').read()
TREE = ast.parse(SRC)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

def fn(name):
    f = next(n for n in ast.walk(TREE)
             if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SRC, f) or ''

# ── the server side ───────────────────────────────────────────────────────
prices = fn('api_market_prices')
check('there is one endpoint that answers for many pools at once, so a screen '
      'of tokens costs one upstream request rather than one per card',
      "','.join(wanted)" in prices)
check('...capped at the 30 addresses DexScreener will take, so a longer list '
      'cannot turn into a request that fails outright',
      'len(wanted) >= 30' in prices)
check('...with duplicates dropped, since the same pool can appear on screen '
      'more than once', 'seen' in prices and 'not in seen' in prices)

check('addresses are validated for the chain they claim to be on, never '
      'pasted into a URL as sent — this builds an outbound request out of '
      'something a caller controls',
      '_addr_ok(' in prices and 'is_valid_evm_address' in prices
      and '_SOLANA_ADDR_RE' in prices)
check('...and an unknown chain is refused before anything is fetched',
      prices.index('EVM_CHAINS and chain') < prices.index('_dex_get'))

ttl = re.search(r'_LIVE_PRICE_TTL\s*=\s*(\d+)', SRC)
check('a live price is cached briefly rather than not at all, so every viewer '
      'of the same token collapses into one upstream request',
      ttl and 1 <= int(ttl.group(1)) <= 10)
check('...and that window is what the endpoint actually asks for',
      'ttl_override=_LIVE_PRICE_TTL' in prices)
check('a failed price fetch is quiet, leaving the chart showing what it drew '
      'before — this is movement on top of the candles, not the candles',
      'except Exception' in prices and "'prices': {}" in prices)
check('...and it is rate limited like every other public endpoint',
      '@rate_limit' in SRC[SRC.index('def api_market_prices') - 200:
                           SRC.index('def api_market_prices')])

# ── the page ──────────────────────────────────────────────────────────────
check('the page runs ONE price ticker for the whole screen, not one per card',
      JS.count('startLivePrices()') == 2      # the definition, and one call
      and 'if(_priceTimer) return;' in JS)
check('...batching every visible chart into a request per chain',
      'byChain' in JS and 'pairs.join(\',\')' in JS)

tick = JS[JS.index('function tickLivePrices'):]
tick = tick[:tick.index('function startLivePrices')]
check('a chart redraws from the candles it already has, so a price tick costs '
      'no candle fetch at all', 'st.candles' in tick and 'fetchChart' not in tick)
check('...moving the newest candle, which is the one still forming — its '
      'close IS the current price', 'last.c = px' in tick)
check('...and stretching its high and low to match, or the wick would end up '
      'outside its own candle',
      'if(px > last.h) last.h = px;' in tick and 'if(px < last.l) last.l = px;' in tick)
check('...and skipping a redraw when the price has not changed, so an '
      'unchanged chart is not repainted every four seconds',
      'px === st.price' in tick)

check('nothing is asked for while the tab is in the background — that is how '
      'a page gets rate limited for charts nobody is looking at',
      "document.visibilityState === 'visible'" in JS)

# ── and the candle polling that this makes unnecessary ────────────────────
m = re.search(r'chartTick\(idx\); \}, (\d+)\);', JS)
check('the candles are no longer polled harder than the server will answer. '
      'They were fetched every 5s against a 30s cache — six identical replies '
      'for one answer', m and int(m.group(1)) >= 15000)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
