"""The spend ceiling and the zero-subsidy rule.

These are the two rules the whole trade engine exists to enforce, so they
are tested against the real functions rather than a description of them.

Most of these assert a refusal. That is the point: the failure mode this
replaces is a trade that goes through and costs more than the user agreed
to, or costs OrcAgent money nobody charged for. Both look like success from
the outside, which is why they need a test that says no.
"""
import sys
from decimal import Decimal

sys.path.insert(0, '/home/user/Orc-agent-Solana-chain-')

from trade_engine.costs import (          # noqa: E402
    CostLine, CostError, Quote, price_trade, reconcile, sponsored_gas, money,
    KIND_BRIDGE_FEE, KIND_DEX_FEE, KIND_SLIPPAGE_RESERVE, KIND_SOURCE_GAS,
    KIND_DEST_GAS, KIND_PLATFORM_FEE, PAYER_ORCAGENT, PAYER_USER, ZERO,
)
from trade_engine import registry as R    # noqa: E402

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

D = Decimal
FEE = '0.0075'          # the rate the app actually runs (FEE_RATE_TXN)


# ════════════════════════════════════════════════════════════════
# 1. The ceiling
# ════════════════════════════════════════════════════════════════
q = price_trade('100', FEE, [
    CostLine(KIND_BRIDGE_FEE, D('1.20'), source='bridge'),
    sponsored_gas(D('0.35'), recovered=True),
    CostLine(KIND_DEX_FEE, D('0.15'), source='0x'),
    CostLine(KIND_SLIPPAGE_RESERVE, D('0.30')),
], same_chain=False)

check('$100 in, $100 out — the ceiling is met exactly, not approached',
      q.total_user_spend_usd == D('100.00'))
check('the purchase is the REMAINDER, not the input — this is the whole '
      'change from how the app works today', q.token_purchase_usd == D('97.27'))
check('the trade is allowed', q.can_execute and q.reject_reason is None)
check('OrcAgent pays nothing', q.subsidy_usd == ZERO)

check('every cost is itemised, fee included',
      {c.kind for c in q.costs} == {KIND_BRIDGE_FEE, KIND_SOURCE_GAS, KIND_DEX_FEE,
                                    KIND_SLIPPAGE_RESERVE, KIND_PLATFORM_FEE})

# The fee is a percentage of the PURCHASE, not of the entered amount. Taking
# it on the entered amount charges for money never spent on the token.
fee_line = [c for c in q.costs if c.kind == KIND_PLATFORM_FEE][0]
check('the fee is charged on the purchase, not on the amount typed',
      fee_line.usd == D('0.73') and fee_line.usd < money('100') * money(FEE))
check('...and the arithmetic closes: purchase + fee + costs == ceiling',
      q.token_purchase_usd + q.user_costs_usd == D('100.00'))


# ════════════════════════════════════════════════════════════════
# 2. Step 35 — the critical subsidy tests
# ════════════════════════════════════════════════════════════════
q = price_trade('100', FEE, [CostLine(KIND_BRIDGE_FEE, D('2.00'), source='bridge')])
check('max spend $100, costs about $2 → executes', q.can_execute)
check('...and stays inside the ceiling', q.total_user_spend_usd <= D('100'))

q = price_trade('100', FEE, [CostLine(KIND_BRIDGE_FEE, D('101.00'), source='bridge')])
check('max spend $100, costs $101 → REFUSED, nothing is bought', not q.can_execute)
check('...with nothing left to purchase', q.token_purchase_usd == ZERO)
check('...and a reason a user can act on', 'larger amount' in (q.reject_reason or ''))
check('...and it never runs a negative purchase to make the sum work',
      q.token_purchase_usd >= ZERO)

q = price_trade('100', FEE, [CostLine(KIND_BRIDGE_FEE, D('100.00'), source='bridge')])
check('costs of exactly the whole budget leave nothing to buy with → refused',
      not q.can_execute)

# The subsidy rule is independent of the ceiling: this one fits comfortably
# and is still refused, because OrcAgent would be paying.
q = price_trade('100', FEE, [sponsored_gas(D('0.35'), recovered=False)])
check('a trade well inside budget is STILL refused when OrcAgent pays the gas — '
      'fitting the ceiling is not the same as costing OrcAgent nothing',
      q.fits_ceiling and not q.can_execute)
check('...the subsidy is reported as a number, not just a flag',
      q.subsidy_usd == D('0.35'))
check('...and the reason says who would be paying',
      'OrcAgent' in (q.reject_reason or ''))

# Same gas, recovered — the sponsor becomes a payment rail.
q = price_trade('100', FEE, [sponsored_gas(D('0.35'), recovered=True)])
check('the SAME sponsored gas, charged to the user, executes fine — technical '
      'sponsor and economic payer are different questions', q.can_execute)
check('...it is still recorded as sponsored, so the sponsor wallet can be repaid',
      any(c.sponsored and c.payer == PAYER_USER for c in q.costs))
check('...and it is not counted as subsidy', q.subsidy_usd == ZERO)

# An OrcAgent-paid cost must never be quietly financed out of the purchase.
q = price_trade('100', FEE, [sponsored_gas(D('5.00'), recovered=False)])
check('an OrcAgent-paid cost does not shrink the purchase — that would hide the '
      'subsidy as a smaller trade', q.token_purchase_usd == D('99.25'))


# ════════════════════════════════════════════════════════════════
# 3. Reconciliation — what really happened
# ════════════════════════════════════════════════════════════════
q = price_trade('100', FEE, [CostLine(KIND_BRIDGE_FEE, D('1.00'), source='bridge')])
r = reconcile(q, [CostLine(KIND_BRIDGE_FEE, D('1.00'), source='bridge'),
                  CostLine(KIND_PLATFORM_FEE, D('0.73'))], D('96.27'))
check('a trade that came in under budget releases the difference',
      r['release_to_user_usd'] == '2.00' and r['ceiling_held'])
check('...and needs no investigation', not r['needs_investigation'])

r = reconcile(q, [CostLine(KIND_BRIDGE_FEE, D('4.00'), source='bridge')], D('99.00'))
check('a trade that ended up over the ceiling is flagged, not absorbed',
      not r['ceiling_held'] and r['needs_investigation'] and r['overspend_usd'] == '3.00')
check('...and releases nothing rather than a negative amount',
      r['release_to_user_usd'] == '0')

r = reconcile(q, [CostLine(KIND_SOURCE_GAS, D('0.40'), payer=PAYER_ORCAGENT,
                           source='gas_sponsor')], D('90.00'))
check('gas that turned out higher than quoted and fell to OrcAgent is flagged '
      'even though the user stayed under budget',
      r['ceiling_held'] and r['needs_investigation'] and r['orcagent_subsidy_usd'] == '0.40')


# ════════════════════════════════════════════════════════════════
# 4. Money is Decimal, and floats are refused at the door
# ════════════════════════════════════════════════════════════════
try:
    money(100.5); ok = False
except CostError:
    ok = True
check('a float is refused as a money amount rather than silently converted — '
      'Decimal(0.1) carries a tail that survives every later multiplication', ok)

try:
    CostLine(KIND_DEX_FEE, 1.5); ok = False
except CostError:
    ok = True
check('...including inside a cost line', ok)

try:
    CostLine(KIND_DEX_FEE, D('-1')); ok = False
except CostError:
    ok = True
check('a negative cost is refused — a "cost" that pays money back is a bug, '
      'and it would silently raise the ceiling', ok)

check('a string amount is accepted and exact', money('0.1') + money('0.2') == D('0.3'))

# Rounding must go the safe way in both directions.
for amount in ('10', '33.33', '99.99', '100', '250.55', '1000', '7.77'):
    qq = price_trade(amount, FEE, [CostLine(KIND_DEX_FEE, D('0.17'), source='0x')])
    if qq.token_purchase_usd > ZERO:
        assert qq.total_user_spend_usd <= money(amount), amount
check('across a spread of amounts the total NEVER exceeds the ceiling — rounding '
      'goes down on the purchase and up on the costs, never the reverse', True)

qq = price_trade('0.01', FEE, [CostLine(KIND_DEX_FEE, D('0.17'), source='0x')])
check('an amount too small to cover its own costs is refused, not rounded into '
      'existence', not qq.can_execute)


# ════════════════════════════════════════════════════════════════
# 5. Double counting
# ════════════════════════════════════════════════════════════════
q = price_trade('100', FEE, [
    CostLine(KIND_DEX_FEE, D('0.15'), source='0x'),
    CostLine(KIND_BRIDGE_FEE, D('1.00'), source='bridge'),
])
check('every cost records where its figure came from, so a fee already inside a '
      'provider quote can be spotted instead of added twice',
      {c.source for c in q.costs} == {'0x', 'bridge', 'orcagent'})
check('the breakdown groups by kind for the UI without losing the per-line detail',
      q.breakdown()['costs_by_kind'][KIND_DEX_FEE] == '0.15'
      and len(q.breakdown()['costs']) == 3)


# ════════════════════════════════════════════════════════════════
# 6. The registry — chain + address, and real decimals
# ════════════════════════════════════════════════════════════════
check('BSC USDC is 18 decimals, not the 6 it has everywhere else — assuming 6 '
      'here is a 10^12 sizing error',
      R.get_chain('bsc').stable.decimals == 18)
check('Base USDC really is 6', R.get_chain('base').stable.decimals == 6)
check('Solana USDC is 6 and SOL is 9',
      R.get_chain('solana').stable.decimals == 6
      and R.get_chain('solana').native.decimals == 9)
check('Robinhood Chain funds trades in USDG, not USDC',
      R.get_chain('robinhood').stable.symbol == 'USDG')

try:
    R.get_chain('robinhood').stable.require_decimals(); ok = False
except R.UnknownDecimals:
    ok = True
check('an asset whose decimals were never verified RAISES instead of returning a '
      'plausible default — the app reads decimals() from the contract for this', ok)

check('Solana has no EVM chain id, and that absence is not faked with a number',
      R.get_chain('solana').chain_id is None and R.get_chain('bsc').chain_id == 56)

try:
    R.get_chain('ethereum'); ok = False
except R.RegistryError:
    ok = True
check('a chain the platform does not trade raises rather than falling through', ok)

check('same-chain is decided through the registry, so a misspelled chain cannot '
      'read as "different" and route a same-chain trade over a bridge',
      R.is_same_chain('base', 'base') and not R.is_same_chain('base', 'bsc'))

# Raw unit conversion, where the classic float bug lives.
usdc_bsc = R.get_chain('bsc').stable
check('0.1 USDC on BSC converts to exactly 10^17 base units',
      R.to_raw(D('0.1'), usdc_bsc) == 10**17)
check('...and back again without drift', R.from_raw(10**17, usdc_bsc) == D('0.1'))

try:
    R.to_raw(0.1, usdc_bsc); ok = False
except R.RegistryError:
    ok = True
check('a float is refused for base-unit conversion — int(0.1 * 10**18) is '
      '99999999999999998, one wei short, discovered months later', ok)

try:
    R.to_raw(D('0.0000001'), R.get_chain('base').stable); ok = False
except R.RegistryError:
    ok = True
check('an amount with more precision than the token can hold raises instead of '
      'being silently truncated', ok)


# ════════════════════════════════════════════════════════════════
# 7. Nothing here touches the running app
# ════════════════════════════════════════════════════════════════
import trade_engine.costs as _c, trade_engine.registry as _r   # noqa: E402
src = open(_c.__file__).read() + open(_r.__file__).read()
for forbidden in ('import dashboard', 'sqlite3', 'requests', 'web3', 'os.environ'):
    check(f'the cost engine does not reach for {forbidden} — it is pure arithmetic '
          f'and can be tested without starting anything', forbidden not in src)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
