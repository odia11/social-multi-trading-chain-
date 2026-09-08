"""Normalising provider quotes without charging anything twice.

The adapters wrap the app's existing 0x and Jupiter calls rather than
replacing them, so what is tested here is the translation: does a real
response shape come out as the right costs, and — the expensive question —
does a fee the provider already priced in get added a second time?

Every provider response below is the shape the real APIs return. No network:
the fetch function is injected, which is the reason it is injected.
"""
import sys
from decimal import Decimal

sys.path.insert(0, '/home/user/Orc-agent-Solana-chain-')

from trade_engine import registry as R                       # noqa: E402
from trade_engine.costs import KIND_DEX_FEE, KIND_SLIPPAGE_RESERVE  # noqa: E402
from trade_engine.providers import (                          # noqa: E402
    JupiterProvider, ProviderError, ZeroExProvider, costs_from_swap_quote,
)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

D = Decimal
BASE = R.get_chain('base')
USDC_BASE = BASE.stable
TOKEN = '0x4200000000000000000000000000000000000006'
TAKER = '0x1111111111111111111111111111111111111111'


# ── 0x, in the shape Swap API v2 actually replies ──
def zx_ok(sell, buy, amount, taker, chain):
    return {
        'buyAmount': '1000000000000000000',
        'minBuyAmount': '990000000000000000',      # 1% slippage tolerance
        'estimatedPriceImpact': '0.42',
        'transaction': {'gas': '210000', 'gasPrice': '15000000'},
    }

zx = ZeroExProvider(zx_ok)
q = zx.quote(chain='base', sell_asset=USDC_BASE, buy_address=TOKEN,
             sell_amount_raw=100_000_000, taker=TAKER)

check('a 0x response becomes a normalised quote', q.provider == '0x' and q.chain == 'base')
check('the guaranteed minimum is kept separately from the expected output — they '
      'are different promises', q.buy_amount_raw == 10**18 and q.min_buy_amount_raw == 99 * 10**16)
check('the slippage gap is the difference between them',
      q.slippage_reserve_raw == 10**18 - 99 * 10**16)
check('gas is derived from the transaction block, in native units',
      q.estimated_gas_native == D('210000') * D('15000000') / D(10) ** 18)
check('the quote states that its DEX fee is already included',
      KIND_DEX_FEE in q.included_kinds)

lines = costs_from_swap_quote(q)
kinds = {c.kind for c in lines}
check('NO dex fee is added — 0x prices its router fee into buyAmount, and adding '
      'one here would charge the user twice for the same thing',
      KIND_DEX_FEE not in kinds)
check('the slippage reserve IS added, because no aggregator prices it in',
      KIND_SLIPPAGE_RESERVE in kinds)
check('the reserve is valued in the dollar asset the trade is funded with, so it '
      'is in the same currency as the ceiling',
      lines[0].usd == D('1.00'))          # 1% of a $100 sell
check('...and is labelled a reserve that comes back, not a fee',
      'released if unused' in lines[0].detail)
check('the reserve names the provider it came from', lines[0].source == '0x')


# ── refusals: a provider that cannot answer must not become a zero ──
def zx_no_route(*a, **k):
    return {'liquidityAvailable': False}

try:
    ZeroExProvider(zx_no_route).quote(chain='base', sell_asset=USDC_BASE,
                                      buy_address=TOKEN, sell_amount_raw=1, taker=TAKER)
    ok = False
except ProviderError:
    ok = True
check('a quote with no buyAmount raises "no route" instead of being read as an '
      'output of zero', ok)

def zx_boom(*a, **k):
    raise RuntimeError('502 from upstream')

try:
    ZeroExProvider(zx_boom).quote(chain='base', sell_asset=USDC_BASE,
                                  buy_address=TOKEN, sell_amount_raw=1, taker=TAKER)
    ok = False
except ProviderError as e:
    ok = '502' in str(e)
check('a provider outage surfaces as a ProviderError carrying the real cause', ok)

try:
    zx.quote(chain='solana', sell_asset=USDC_BASE, buy_address=TOKEN,
             sell_amount_raw=1, taker=TAKER)
    ok = False
except ProviderError:
    ok = True
check('0x is refused for Solana rather than asked and failing obscurely', ok)

def zx_no_gas(sell, buy, amount, taker, chain):
    return {'buyAmount': '100', 'minBuyAmount': '100'}

q2 = ZeroExProvider(zx_no_gas).quote(chain='base', sell_asset=USDC_BASE,
                                     buy_address=TOKEN, sell_amount_raw=1, taker=TAKER)
check('a quote with no readable gas reports gas as UNKNOWN, not as zero — a zero '
      'would silently drop a real cost out of the ceiling',
      q2.estimated_gas_native is None)
check('a quote with no slippage gap adds no reserve',
      costs_from_swap_quote(q2) == [])


# ── Jupiter ──
def jup_ok(sell, buy, amount):
    return {'outAmount': '500000000', 'otherAmountThreshold': '495000000',
            'priceImpactPct': '0.0031'}

jq = JupiterProvider(jup_ok).quote(chain='solana', sell_asset=R.get_chain('solana').stable,
                                   buy_address='So11111111111111111111111111111111111111112',
                                   sell_amount_raw=100_000_000, taker='x')
check('a Jupiter response becomes the same normalised shape as a 0x one',
      jq.provider == 'jupiter' and jq.buy_amount_raw == 500_000_000)
check('otherAmountThreshold is read as the guaranteed minimum',
      jq.min_buy_amount_raw == 495_000_000)
check('Jupiter reports price impact as a fraction; it is normalised to a percent',
      jq.price_impact_pct == D('0.31'))
check('Jupiter reports no gas estimate rather than inventing one — Solana network '
      'fees are handled on the existing swap path', jq.estimated_gas_native is None)
check('its DEX fee is also already included', KIND_DEX_FEE in jq.included_kinds)

try:
    JupiterProvider(jup_ok).quote(chain='base', sell_asset=USDC_BASE,
                                  buy_address=TOKEN, sell_amount_raw=1, taker='x')
    ok = False
except ProviderError:
    ok = True
check('Jupiter is refused for an EVM chain', ok)


# ── the double-counting guard itself ──
class Vague:
    pass

vague = q
object.__setattr__(vague, 'included_kinds', frozenset())
try:
    costs_from_swap_quote(vague)
    ok = False
except ProviderError as e:
    ok = 'twice' in str(e)
check('a provider that does not say whether its DEX fee is included is REFUSED '
      'rather than guessed at — guessing wrong charges the user twice', ok)


# ── the adapters stay out of the app ──
# Checked against the CODE, not the file text: these module names appear in
# the comments explaining which integration each adapter wraps, and matching
# those would pass or fail for the wrong reason.
import ast, trade_engine.providers as _p                       # noqa: E402
tree = ast.parse(open(_p.__file__).read())
imported = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        imported.update(a.name.split('.')[0] for a in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module:
        imported.add(node.module.split('.')[0])
for forbidden in ('dashboard', 'requests', 'orcagent_solana', 'web3', 'sqlite3'):
    check(f'the adapters do not import {forbidden} — the real call is injected, '
          f'which is what makes them testable without a network', forbidden not in imported)

called = {n.func.attr for n in ast.walk(tree)
          if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
check('nothing here signs or broadcasts a transaction — quoting only',
      not {'send_raw_transaction', 'sign_transaction', 'sendTransaction'} & called)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
