"""OrcAgent's SOL price is always SOL's price -- or none, never a guess.

The deploy check failed with "SOL price feed: no usable SOL/USDC pair in the
feed response": DexScreener now and then answers right after a restart with
no pairs. Looking at it showed a worse risk in the app itself: when no
SOL/USDC pair came back it took "the first pair" -- and DexScreener's answer
for SOL also lists TOKEN/SOL pairs, whose price is that token's. A memecoin
at $1.97 would have become the SOL price, and the first SOL price the app
sees also converts old users' trade sizes to dollars.

Now one function prices SOL for the app and the deploy check: only SOL/USDC
and SOL/USDT pairs, deepest first; Jupiter when DexScreener has nothing
usable; 0 when neither answers. The deploy check tries three times.
"""
import ast, os

ROOT = os.path.join(os.path.dirname(__file__), '..')
SRC = open(os.path.join(ROOT, 'dashboard.py'), encoding='utf-8').read()
VERIFY = open(os.path.join(ROOT, 'tools', 'verify_live.py'), encoding='utf-8').read()
found = {}
for node in ast.parse(SRC).body:
    if isinstance(node, ast.FunctionDef) and node.name in ('_sol_usd_from_pairs', '_fetch_sol_price_usd'):
        found[node.name] = ast.get_source_segment(SRC, node)
    elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) \
            and node.targets[0].id in ('_SOL_USD_QUOTES', 'SOL_MINT', 'USDC_MINT'):
        found[node.targets[0].id] = ast.get_source_segment(SRC, node)
assert len(found) == 5, 'missing in dashboard.py: %s' % sorted({'_sol_usd_from_pairs', '_fetch_sol_price_usd', '_SOL_USD_QUOTES', 'SOL_MINT', 'USDC_MINT'} - set(found))

checks = []
def check(name, cond, detail=''):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name + ((' -- %s' % detail) if detail and not cond else ''))

SOL, USDC = 'So11111111111111111111111111111111111111112', 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
USDT, WIF = 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB', 'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm'
def pair(base, quote, price, liq):
    return {'baseToken': {'address': base}, 'quoteToken': {'address': quote}, 'priceUsd': str(price), 'liquidity': {'usd': liq}}


class Resp:
    def __init__(self, status, payload):
        self.status_code, self._p = status, payload
    def json(self):
        return self._p


class FakeRequests:
    RequestException = Exception
    def __init__(self):
        self.answer = None
        self.calls = []
    def get(self, url, **kw):
        self.calls.append(url)
        if self.answer is None:
            raise self.RequestException('down')
        return Resp(200, self.answer)


DEX = {'answer': None}
fake_requests = FakeRequests()
ns = {'requests': fake_requests, '_dex_get': lambda url, timeout=10: DEX['answer']}
for name in ('SOL_MINT', 'USDC_MINT', '_SOL_USD_QUOTES', '_sol_usd_from_pairs', '_fetch_sol_price_usd'):
    exec(found[name], ns)
from_pairs, fetch = ns['_sol_usd_from_pairs'], ns['_fetch_sol_price_usd']

check('SOL/USDC pairs: the deepest one gives the price',
      from_pairs([pair(SOL, USDC, 115.5, 1e6), pair(SOL, USDC, 116.11, 3e7), pair(SOL, USDT, 116.3, 2e6)]) == 116.11)
check('a TOKEN/SOL pair is never taken as the SOL price (it was, as "the first pair")',
      from_pairs([pair(WIF, SOL, 1.97, 9e7)]) == 0.0)
check('a SOL pair quoted in something else is not either', from_pairs([pair(SOL, WIF, 59.0, 1e6)]) == 0.0)
check('no pairs at all (DexScreener answering "pairs": null) gives no price', from_pairs(None) == 0.0)

DEX['answer'] = Resp(200, {'pairs': [pair(SOL, USDC, 116.11, 3e7), pair(WIF, SOL, 1.97, 9e7)]})
check('the app prices SOL from DexScreener when it answers', fetch() == 116.11 and not fake_requests.calls)
DEX['answer'] = Resp(200, {'schemaVersion': '1.0.0', 'pairs': None})
fake_requests.answer = {SOL: {'usdPrice': 116.4}}
check('...and from Jupiter when DexScreener has no usable pair', fetch() == 116.4 and fake_requests.calls)
fake_requests.answer = None
DEX['answer'] = None
check('...and gives no price, not a guess, when neither answers', fetch() == 0.0)

check('the app uses it, and nothing picks "the first pair" any more',
      '_sp = _fetch_sol_price_usd()' in SRC and "_pairs[0] if _pairs else None" not in SRC)
check('the deploy check uses the same function and tries three times',
      'd._fetch_sol_price_usd()' in VERIFY and 'for attempt_no in range(3):' in VERIFY
      and "pairs[0] if pairs else None" not in VERIFY)

print('%d/%d' % (sum(checks), len(checks)))
raise SystemExit(0 if all(checks) else 1)
