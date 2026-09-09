"""Building a quote: the ceiling, the expiry, and the circular reserve.

The interesting case here is the one that has no clean answer. Quoting a
swap needs an amount; the amount is what remains after costs; one of the
costs only exists once the swap is quoted. These check that the loop is
broken in the conservative direction — the ceiling holds with room to spare,
rather than by a hair — and that it terminates instead of iterating.

Everything is injected: gas, bridge and swap are functions this file
provides, so there is no network and the numbers are exact.
"""
import sys
from decimal import Decimal

sys.path.insert(0, '/home/user/Orc-agent-Solana-chain-')

from trade_engine import registry as R                      # noqa: E402
from trade_engine.costs import PAYER_ORCAGENT, ZERO         # noqa: E402
from trade_engine.providers import ProviderError, ZeroExProvider  # noqa: E402
from trade_engine.quote import (                            # noqa: E402
    QUOTE_TTL_SECONDS, QuoteError, QuoteRequest, build_quote,
)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

D = Decimal
FEE = '0.0075'
TOKEN = '0x4200000000000000000000000000000000000006'


def req(**kw):
    base = dict(user_id=1, wallet='W', source_chain='base', destination_chain='base',
                token_address=TOKEN, max_spend_usd=D('100'), taker_address='0xabc')
    base.update(kw)
    return QuoteRequest(**base)


def swap_returning(buy='1000000000000000000', minimum='990000000000000000'):
    def fetch(sell, buy_addr, amount, taker, chain):
        return {'buyAmount': buy, 'minBuyAmount': minimum,
                'transaction': {'gas': '200000', 'gasPrice': '10000000'}}
    return ZeroExProvider(fetch)


FIXED_TIME = [1_000_000.0]
def clock():
    return FIXED_TIME[0]


# ════════════════════════════════════════════════════════════════
# 1. Same chain — the fast path
# ════════════════════════════════════════════════════════════════
q = build_quote(req(), swap_provider=swap_returning(),
                gas_estimator=lambda c: D('0.35'), fee_rate=FEE, clock=clock)

check('a same-chain trade is marked same-chain', q.same_chain)
check('...and its route names no bridge at all — this is the whole point of the '
      'fast path', 'bridge' not in q.route)
check('the total never exceeds the ceiling',
      q.priced.total_user_spend_usd <= D('100'))
check('OrcAgent pays nothing', q.priced.subsidy_usd == ZERO)
check('the quote is executable', q.priced.can_execute)
check('the swap is quoted through the provider, and its identity is recorded',
      q.swap is not None and q.to_dict(clock())['swap_provider'] == '0x')
check('the guaranteed minimum output is carried through for the execute step',
      q.to_dict(clock())['minimum_output_raw'] == '990000000000000000')

d = q.to_dict(clock())
check('the breakdown itemises every cost the user pays',
      set(d['costs_by_kind']) == {'source_gas', 'slippage_reserve', 'platform_fee'})
check('...and reports the purchase as the remainder, not the input',
      D(d['token_purchase_usd']) < D('100') and D(d['token_purchase_usd']) > D('95'))
check('timings are recorded for every stage, so a slow provider is identifiable',
      'lookups_ms' in q.timings_ms and 'swap_quote_ms' in q.timings_ms
      and 'total_ms' in q.timings_ms)


# ════════════════════════════════════════════════════════════════
# 2. The circular slippage reserve
# ════════════════════════════════════════════════════════════════
# A 1% tolerance on a ~$99 provisional purchase is a ~$0.99 reserve, which
# then shrinks the purchase. The result must still fit, and must terminate.
check('the reserve is included in the costs, not silently dropped',
      'slippage_reserve' in d['costs_by_kind'])
check('the reserve shrank the purchase, and the quote says so rather than hiding it',
      any('slippage reserve' in w for w in q.warnings))
check('after the second pass the total STILL fits the ceiling — the loop is broken '
      'in the conservative direction', q.priced.total_user_spend_usd <= D('100'))
check('the swap was quoted once, not iterated to a fixed point',
      q.timings_ms.get('swap_quote_ms') is not None)

# A quote with no slippage gap needs no second pass and no warning.
q_tight = build_quote(req(), swap_provider=swap_returning(minimum='1000000000000000000'),
                      gas_estimator=lambda c: D('0.35'), fee_rate=FEE, clock=clock)
check('a swap with no slippage gap adds no reserve and no warning',
      'slippage_reserve' not in q_tight.to_dict(clock())['costs_by_kind']
      and not q_tight.warnings)


# ════════════════════════════════════════════════════════════════
# 3. Sponsored gas — payment rail vs subsidy
# ════════════════════════════════════════════════════════════════
q = build_quote(req(), swap_provider=swap_returning(), gas_estimator=lambda c: D('0.35'),
                fee_rate=FEE, gas_is_sponsored=lambda c: True, clock=clock)
gas_line = [c for c in q.priced.costs if c.kind == 'source_gas'][0]
check('sponsored gas is charged to the user, so the sponsor wallet is a payment '
      'rail and not a benefactor', gas_line.sponsored and gas_line.payer == 'user')
check('...and the quote therefore reports zero subsidy and executes',
      q.priced.subsidy_usd == ZERO and q.priced.can_execute)


# ════════════════════════════════════════════════════════════════
# 4. Cross chain
# ════════════════════════════════════════════════════════════════
q = build_quote(
    req(destination_chain='bsc'), swap_provider=swap_returning(),
    gas_estimator=lambda c: D('0.35'), fee_rate=FEE,
    bridge_quoter=lambda s, d_, usd: {'fee_usd': D('1.20')}, clock=clock)

check('a cross-chain trade is not marked same-chain', not q.same_chain)
check('...its route names the bridge', 'bridge' in q.route)
check('...and it is charged gas on BOTH chains, because it pays gas on both',
      'destination_gas' in q.to_dict(clock())['costs_by_kind'])
check('the bridge fee is itemised separately from gas',
      q.to_dict(clock())['costs_by_kind']['bridge_fee'] == '1.20')
check('the ceiling still holds across all of it', q.priced.total_user_spend_usd <= D('100'))

try:
    build_quote(req(destination_chain='bsc'), swap_provider=swap_returning(),
                gas_estimator=lambda c: D('0.35'), fee_rate=FEE, clock=clock)
    ok = False
except QuoteError as e:
    ok = 'bridge' in str(e)
check('a cross-chain trade with no bridge configured is refused, not quoted as if '
      'it were same-chain', ok)


# ════════════════════════════════════════════════════════════════
# 5. Refusals — a missing number never becomes zero
# ════════════════════════════════════════════════════════════════
def boom(*a, **k):
    raise RuntimeError('rpc down')

try:
    build_quote(req(), swap_provider=swap_returning(), gas_estimator=boom,
                fee_rate=FEE, clock=clock)
    ok = False
except QuoteError as e:
    ok = 'gas' in str(e)
check('gas that cannot be estimated refuses the quote instead of being treated as '
      'free — a zero there quietly drops a real cost out of the ceiling', ok)

try:
    build_quote(req(destination_chain='bsc'), swap_provider=swap_returning(),
                gas_estimator=lambda c: D('0.35'), fee_rate=FEE,
                bridge_quoter=boom, clock=clock)
    ok = False
except QuoteError as e:
    ok = 'bridge route' in str(e)
check('a bridge that cannot quote refuses the trade', ok)

def no_route(*a, **k):
    return {'liquidityAvailable': False}
try:
    build_quote(req(), swap_provider=ZeroExProvider(no_route),
                gas_estimator=lambda c: D('0.35'), fee_rate=FEE, clock=clock)
    ok = False
except QuoteError:
    ok = True
check('a token with no route refuses the quote', ok)

q_broke = build_quote(req(max_spend_usd=D('0.20')), swap_provider=swap_returning(),
                      gas_estimator=lambda c: D('0.35'), fee_rate=FEE, clock=clock)
check('an amount too small to cover its own gas returns a refused quote — and '
      'never calls the swap provider at all', q_broke.swap is None)
check('...saying plainly that there is nothing left to buy with',
      not q_broke.priced.can_execute and 'larger amount' in (q_broke.priced.reject_reason or ''))

try:
    QuoteRequest(user_id=1, wallet='W', source_chain='base', destination_chain='base',
                 token_address=TOKEN, max_spend_usd=100.0, taker_address='x')
    ok = False
except QuoteError:
    ok = True
check('a float max spend is refused at the request boundary', ok)

try:
    build_quote(req(source_chain='ethereum'), swap_provider=swap_returning(),
                gas_estimator=lambda c: D('0.35'), fee_rate=FEE, clock=clock)
    ok = False
except R.RegistryError:
    ok = True
check('a chain the platform does not trade is refused by the registry', ok)


# ════════════════════════════════════════════════════════════════
# 6. Expiry — a quote is a promise about prices that move
# ════════════════════════════════════════════════════════════════
FIXED_TIME[0] = 1_000_000.0
q = build_quote(req(), swap_provider=swap_returning(), gas_estimator=lambda c: D('0.35'),
                fee_rate=FEE, clock=clock)
check('a fresh quote is not expired and reports its remaining life',
      not q.is_expired(clock()) and q.seconds_left(clock()) == QUOTE_TTL_SECONDS)

later = 1_000_000.0 + QUOTE_TTL_SECONDS + 1
check('past its TTL the quote is expired', q.is_expired(later))
d_old = q.to_dict(later)
check('an expired quote reports can_execute FALSE whatever its numbers said when '
      'it was made', d_old['can_execute'] is False)
check('...and says so in words', 'expired' in d_old['reject_reason'].lower())
check('...and reports zero seconds left rather than a negative number',
      d_old['expires_in_seconds'] == 0)


# ════════════════════════════════════════════════════════════════
# 7. Still nothing that can execute
# ════════════════════════════════════════════════════════════════
import ast, trade_engine.quote as _q                          # noqa: E402
tree = ast.parse(open(_q.__file__).read())
imported = set()
for n in ast.walk(tree):
    if isinstance(n, ast.Import):
        imported.update(a.name.split('.')[0] for a in n.names)
    elif isinstance(n, ast.ImportFrom) and n.module:
        imported.add(n.module.split('.')[0])
for forbidden in ('dashboard', 'requests', 'web3', 'sqlite3'):
    check(f'the quote engine does not import {forbidden}', forbidden not in imported)
called = {n.func.attr for n in ast.walk(tree)
          if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
check('nothing here signs or broadcasts',
      not {'send_raw_transaction', 'sign_transaction', 'sendTransaction'} & called)

# ── closing the decimals gap honestly ──────────────────────────────────────
# The registry refuses to guess: an asset nobody has confirmed stays None and
# raises. Robinhood Chain's USDG was the one in that state, and on the first
# live run it did exactly that. The gap closes by READING the contract, not by
# somebody typing a plausible number into the file.
import importlib                                                  # noqa: E402
R2 = importlib.reload(__import__('trade_engine.registry', fromlist=['x']))

check('the registry can name what it has not verified, so the gap is findable '
      'before a trade hits it rather than during one',
      any(a.symbol == 'USDG' for a in R2.unverified_assets()))

usdg = '0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168'
filled = R2.verify_decimals('robinhood', usdg, 6, 'test contract')
check('a value read from the contract fills the blank', filled.decimals == 6)
check('...and is recorded as verified, with where it came from, so the next '
      'reader knows it was measured rather than assumed',
      'verified 6 from test contract' in filled.note)
check('...leaving nothing unverified', not R2.unverified_assets())
check('re-reading the same value is fine',
      R2.verify_decimals('robinhood', usdg, 6, 'test contract').decimals == 6)

try:
    R2.verify_decimals('robinhood', usdg, 18, 'a lying rpc')
    ok = False
except R2.RegistryError:
    ok = True
check('a DIFFERENT answer is refused rather than accepted. A runtime lookup '
      'must not be able to resize every trade on a chain because one RPC '
      'replied wrongly', ok)

try:
    R2.verify_decimals('bsc', '0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d', 6, 'x')
    ok = False
except R2.RegistryError:
    ok = True
check("...and an already-verified value cannot be overwritten either — BSC's "
      '18-decimal USDC is the asset this whole registry exists for', ok)

for bad in (6.0, True, -1, 99, '6'):
    try:
        R2.verify_decimals('robinhood', usdg, bad, 'x')
        ok = False
    except R2.RegistryError:
        ok = True
    check(f'{bad!r} is refused as a decimals value', ok)

try:
    R2.verify_decimals('bsc', '0xdeadbeef', 6, 'x')
    ok = False
except R2.RegistryError:
    ok = True
check("an address that is not the chain's native or stable asset is refused, "
      'rather than silently recording decimals for something the registry '
      'does not track', ok)

# ── gas priced for the route, not for topping a wallet up ──────────────────
# Pass one has no route yet, so it uses a constant sized to FUND a wallet for
# a worst-case approve-plus-swap. That is the right number to top someone up
# with and far too large to price a trade with: on a $1 trade on Robinhood it
# showed $0.27 of network fee, leaving $0.71 of a dollar. The swap quote knows
# what this route actually costs, and pass two now uses it.
from trade_engine.quote import build_quote as _bq, QuoteRequest as _QR   # noqa: E402
from trade_engine.providers import ZeroExProvider as _ZX                # noqa: E402
from decimal import Decimal as _D                                       # noqa: E402


def _route(gas_units, gas_price):
    def f(sell, buy, amount, taker, chain):
        return {'buyAmount': '1000000000000000000',
                'minBuyAmount': '990000000000000000',
                'transaction': {'gas': str(gas_units), 'gasPrice': str(gas_price)}}
    return f


def _price(gas_units, **kw):
    return _bq(_QR(user_id=1, wallet='W', source_chain='base', destination_chain='base',
                   token_address='0xTOKEN', max_spend_usd=_D('100'), taker_address='0xT'),
               swap_provider=_ZX(_route(gas_units, 10 ** 9)),
               gas_estimator=lambda c: _D('0.50'),      # the conservative one
               fee_rate=_D('0.0075'), **kw)


conservative = _price(200000).to_dict()
check('without a converter the pre-swap estimate stands, so nothing changes for '
      'a caller that does not supply one',
      conservative['costs_by_kind']['source_gas'] == '0.50')

# 200000 units at 1 gwei = 0.0002 ETH; at $2000 that is $0.40.
real = _price(200000, gas_from_native=lambda c, n: n * _D('2000')).to_dict()
check("the route's own gas estimate replaces the conservative one",
      real['costs_by_kind']['source_gas'] == '0.40')
check('...leaving MORE to buy with, which on a small trade is the difference '
      'between a sensible cost and half the order',
      _D(real['token_purchase_usd']) > _D(conservative['token_purchase_usd']))
check('...and the ceiling still holds exactly',
      _D(real['token_purchase_usd'])
      + sum(_D(v) for v in real['costs_by_kind'].values()) == _D('100'))
check('...recorded as coming from the route, not from a constant',
      any(c['source'] == '0x' for c in real['costs'] if c['kind'] == 'source_gas'))
check('...and reads as a currency figure. A native amount times a price has as '
      'many decimals as it likes; "0.4000" is not an amount of money',
      len(real['costs_by_kind']['source_gas'].split('.')[1]) == 2)

cheap = _price(80000, gas_from_native=lambda c, n: n * _D('2000')).to_dict()
check('a cheaper route prices cheaper — the figure tracks the actual estimate '
      'rather than a fixed headroom',
      _D(cheap['costs_by_kind']['source_gas']) < _D(real['costs_by_kind']['source_gas']))


def _no_gas(sell, buy, amount, taker, chain):
    return {'buyAmount': '1000000000000000000', 'minBuyAmount': '990000000000000000'}


unknown = _bq(_QR(user_id=1, wallet='W', source_chain='base', destination_chain='base',
                  token_address='0xTOKEN', max_spend_usd=_D('100'), taker_address='0xT'),
              swap_provider=_ZX(_no_gas), gas_estimator=lambda c: _D('0.50'),
              fee_rate=_D('0.0075'),
              gas_from_native=lambda c, n: n * _D('2000')).to_dict()
check('a provider that reports no gas keeps the conservative figure — an '
      'unreadable estimate is unknown, never a cheaper guess',
      unknown['costs_by_kind']['source_gas'] == '0.50')


def _boom(c, n):
    raise RuntimeError('no price feed')

broken = _price(200000, gas_from_native=_boom).to_dict()
check('a converter that fails keeps the conservative figure and says so, rather '
      'than dropping a real cost out of the ceiling',
      broken['costs_by_kind']['source_gas'] == '0.50'
      and any('conservative' in w for w in broken['warnings']))

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
