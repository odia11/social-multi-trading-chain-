"""The spend ceiling, and who actually pays for a trade.

THE RULE
The amount a user types is the maximum TOTAL they spend. Every cost of the
transaction comes out of that number, not on top of it:

    token_purchase + platform_fee + gas + bridge + dex + slippage_reserve
        <= max_spend

and, separately and non-negotiably:

    orcagent_subsidy == 0

The second rule is not implied by the first. A trade can sit comfortably
inside a user's budget while OrcAgent quietly pays the gas for it -- which
is what happens today, because the gas sponsor fronts native tokens and
nothing ever charges them back. So every cost here names its payer, and a
quote where any cost is payable by OrcAgent cannot execute.

THE ARITHMETIC THAT IS EASY TO GET WRONG
The platform fee is a percentage of the trade, and the trade is what is left
after the fee. That is circular, and resolving it naively as
`fee = rate * max_spend` overcharges: it takes the fee on money that was
never spent on the token. Solved properly:

    max_spend = token * (1 + rate) + other_costs
    token     = (max_spend - other_costs) / (1 + rate)

The difference is small per trade and systematic across all of them, which
is the worst shape for an error in a fee.

MONEY IS Decimal, NEVER float
0.1 + 0.2 != 0.3 in binary floating point, and a ceiling enforced on floats
is a ceiling that leaks fractions. Every amount here is a Decimal, floats
are rejected at the door rather than silently converted, and rounding always
goes in the direction that protects the user: costs round UP, the purchase
rounds DOWN. Rounding a purchase up by one cent is how a ceiling gets
exceeded by one cent.

Pure functions. No I/O, no database, no network, no provider calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN, ROUND_UP, getcontext
from typing import Optional

getcontext().prec = 28

CENT = Decimal('0.01')
ZERO = Decimal('0')

# Who ends up out of pocket. Not the same question as who signs the
# transaction: the gas sponsor can be the technical sender while the user is
# the economic payer, which is exactly the arrangement this distinction is
# here to make expressible.
PAYER_USER = 'user'
PAYER_ORCAGENT = 'orcagent'

# Cost kinds, so a breakdown can be summed by category and a provider quote
# that already includes a fee can be recognised instead of counted twice.
KIND_PLATFORM_FEE = 'platform_fee'
KIND_SOURCE_GAS = 'source_gas'
KIND_DEST_GAS = 'destination_gas'
KIND_BRIDGE_FEE = 'bridge_fee'
KIND_DEX_FEE = 'dex_fee'
KIND_SLIPPAGE_RESERVE = 'slippage_reserve'


class CostError(Exception):
    """Raised rather than returning a number that cannot be trusted."""


def money(value) -> Decimal:
    """Coerce to Decimal, refusing floats.

    A float is rejected instead of converted because the conversion is
    lossy in a way that is invisible: Decimal(0.1) is
    0.1000000000000000055511151231257827021181583404541015625, and that tail
    survives every later multiplication.
    """
    if isinstance(value, float):
        raise CostError(
            f'refusing a float ({value!r}) for a money amount — pass a Decimal '
            f'or a string; binary floats cannot represent most decimal values'
        )
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _up(value: Decimal) -> Decimal:
    """Round a cost UP to the cent — never under-state what something costs."""
    return value.quantize(CENT, rounding=ROUND_UP)


def _down(value: Decimal) -> Decimal:
    """Round a purchase DOWN to the cent — never spend a cent over the ceiling."""
    return value.quantize(CENT, rounding=ROUND_DOWN)


@dataclass(frozen=True)
class CostLine:
    """One cost, with its payer and where the figure came from.

    `source` exists to prevent double counting: a 0x quote already includes
    its own router fee, so adding a separately estimated one on top charges
    the user twice for the same thing. Recording the origin makes that
    visible in the breakdown instead of buried in a total.
    """
    kind: str
    usd: Decimal
    payer: str = PAYER_USER
    source: str = 'orcagent'
    sponsored: bool = False      # technically fronted by the sponsor wallet
    detail: str = ''

    def __post_init__(self):
        if isinstance(self.usd, float):
            raise CostError(f'{self.kind}: cost must not be a float')
        if self.usd < ZERO:
            raise CostError(f'{self.kind}: cost cannot be negative ({self.usd})')
        if self.payer not in (PAYER_USER, PAYER_ORCAGENT):
            raise CostError(f'{self.kind}: unknown payer {self.payer!r}')

    @property
    def is_subsidy(self) -> bool:
        """Money OrcAgent does not get back.

        Sponsoring gas is only a subsidy when nobody charges for it. A
        sponsored line whose payer is the user is a loan being repaid out of
        their budget, which is the whole point of keeping the sponsor.
        """
        return self.payer == PAYER_ORCAGENT


def sponsored_gas(usd, recovered: bool, detail: str = '') -> CostLine:
    """Gas the sponsor wallet fronts because the user has no native token.

    `recovered=True` charges it to the user's budget -- the sponsor is then
    a payment rail, not a benefactor. `recovered=False` records the truth
    that OrcAgent is paying, which makes the quote un-executable rather than
    letting the loss through silently.
    """
    return CostLine(
        kind=KIND_SOURCE_GAS,
        usd=money(usd),
        payer=PAYER_USER if recovered else PAYER_ORCAGENT,
        source='gas_sponsor',
        sponsored=True,
        detail=detail or ('recovered from user budget' if recovered
                          else 'NOT recovered — OrcAgent pays this'),
    )


@dataclass
class Quote:
    """A priced trade, and whether it is allowed to execute.

    Construct with `price_trade`; this is not meant to be built by hand,
    because the fee arithmetic is the part that has to be right.
    """
    max_spend_usd: Decimal
    costs: tuple
    token_purchase_usd: Decimal
    fee_rate: Decimal
    same_chain: bool

    # ── totals ──
    @property
    def user_costs_usd(self) -> Decimal:
        return sum((c.usd for c in self.costs if c.payer == PAYER_USER), ZERO)

    @property
    def subsidy_usd(self) -> Decimal:
        """What OrcAgent pays. Must be zero for the trade to run."""
        return sum((c.usd for c in self.costs if c.is_subsidy), ZERO)

    @property
    def total_user_spend_usd(self) -> Decimal:
        """Everything that leaves the user's balance, purchase included."""
        return self.token_purchase_usd + self.user_costs_usd

    @property
    def fits_ceiling(self) -> bool:
        return self.total_user_spend_usd <= self.max_spend_usd

    @property
    def can_execute(self) -> bool:
        """Both rules, together. Either one failing blocks the trade."""
        return (self.fits_ceiling
                and self.subsidy_usd == ZERO
                and self.token_purchase_usd > ZERO)

    @property
    def reject_reason(self) -> Optional[str]:
        """Why not, in words a user can act on."""
        if self.subsidy_usd > ZERO:
            return (f'This route would cost OrcAgent ${self.subsidy_usd} that no '
                    f'one is charged for. Refusing rather than absorbing it.')
        if self.token_purchase_usd <= ZERO:
            return (f'Costs of ${self.user_costs_usd} use up the whole '
                    f'${self.max_spend_usd} — there is nothing left to buy with. '
                    f'Try a larger amount.')
        if not self.fits_ceiling:
            return (f'This route needs ${self.total_user_spend_usd}, which is more '
                    f'than your ${self.max_spend_usd} maximum.')
        return None

    def breakdown(self) -> dict:
        """The shape the quote endpoint and the buy panel both read."""
        by_kind: dict = {}
        for c in self.costs:
            by_kind[c.kind] = by_kind.get(c.kind, ZERO) + c.usd
        return {
            'max_spend_usd': str(self.max_spend_usd),
            'token_purchase_usd': str(self.token_purchase_usd),
            'total_user_spend_usd': str(self.total_user_spend_usd),
            'user_costs_usd': str(self.user_costs_usd),
            'orcagent_subsidy_usd': str(self.subsidy_usd),
            'same_chain': self.same_chain,
            'can_execute': self.can_execute,
            'reject_reason': self.reject_reason,
            'costs': [
                {'kind': c.kind, 'usd': str(c.usd), 'payer': c.payer,
                 'source': c.source, 'sponsored': c.sponsored, 'detail': c.detail}
                for c in self.costs
            ],
            'costs_by_kind': {k: str(v) for k, v in by_kind.items()},
        }


def price_trade(max_spend_usd, fee_rate, other_costs=(), same_chain: bool = True) -> Quote:
    """Price a trade against a hard ceiling.

    `other_costs` are every non-fee cost already known -- gas, bridge, DEX,
    slippage reserve -- as CostLine objects. The platform fee is derived
    here rather than passed in, because it depends on the purchase, which
    depends on the fee.

    Costs payable by OrcAgent are counted but deliberately NOT subtracted
    from the user's budget: subtracting them would quietly turn a subsidy
    into a smaller purchase and hide it. They surface as subsidy_usd
    instead, and block the trade.
    """
    ceiling = money(max_spend_usd)
    rate = money(fee_rate)
    if ceiling < ZERO:
        raise CostError('max spend cannot be negative')
    if rate < ZERO or rate >= Decimal('1'):
        raise CostError(f'fee rate {rate} is not a sensible fraction')

    lines = list(other_costs)
    for line in lines:
        if not isinstance(line, CostLine):
            raise CostError(f'costs must be CostLine, got {type(line).__name__}')

    user_other = sum((c.usd for c in lines if c.payer == PAYER_USER), ZERO)

    # token * (1 + rate) + user_other = ceiling  ->  solve for token.
    # Rounded DOWN so the reconstructed total can only come in under the
    # ceiling, never over it.
    remaining = ceiling - user_other
    if remaining <= ZERO:
        token = ZERO
        fee = ZERO
    else:
        token = _down(remaining / (Decimal('1') + rate))
        # The fee is then taken from the purchase we actually settled on, so
        # the two always agree. Rounded UP, so it is never understated.
        fee = _up(token * rate)
        # Rounding both ways can leave a cent of headroom or overshoot by
        # one; give any spare cent back to the purchase, and take one back
        # from the purchase if the pair went over.
        while token + fee + user_other > ceiling and token > ZERO:
            token -= CENT
            fee = _up(token * rate)

    if fee > ZERO:
        lines.append(CostLine(
            kind=KIND_PLATFORM_FEE, usd=fee, payer=PAYER_USER, source='orcagent',
            detail=f'{(rate * 100).normalize()}% of the token purchase',
        ))

    return Quote(
        max_spend_usd=ceiling,
        costs=tuple(lines),
        token_purchase_usd=token,
        fee_rate=rate,
        same_chain=same_chain,
    )


def reconcile(quote: Quote, actual_costs, actual_token_spend_usd) -> dict:
    """Compare what a trade really cost against what was reserved.

    Called after settlement. Its job is to answer three questions honestly:
    how much to release back to the user, whether the ceiling actually held,
    and whether OrcAgent ended up paying for any of it after all -- which
    can happen even when the quote was clean, if a sponsored cost came in
    above its estimate.
    """
    spent_token = money(actual_token_spend_usd)
    lines = list(actual_costs)
    actual_user = sum((c.usd for c in lines if c.payer == PAYER_USER), ZERO)
    actual_subsidy = sum((c.usd for c in lines if c.is_subsidy), ZERO)
    actual_total = spent_token + actual_user
    release = quote.max_spend_usd - actual_total
    return {
        'actual_total_user_spend_usd': str(actual_total),
        'max_spend_usd': str(quote.max_spend_usd),
        'release_to_user_usd': str(release if release > ZERO else ZERO),
        'ceiling_held': actual_total <= quote.max_spend_usd,
        'overspend_usd': str(actual_total - quote.max_spend_usd
                             if actual_total > quote.max_spend_usd else ZERO),
        'orcagent_subsidy_usd': str(actual_subsidy),
        # An overspend or a subsidy after the fact is not something to
        # absorb quietly -- it means an estimate was wrong and the estimate
        # needs fixing, so it is flagged for a human rather than netted off.
        'needs_investigation': actual_total > quote.max_spend_usd or actual_subsidy > ZERO,
    }
