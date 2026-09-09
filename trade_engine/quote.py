"""Assembling a priced, expiring quote — still without executing anything.

WHAT THIS ADDS OVER costs.py
costs.py answers "given these costs, what fits inside the ceiling". This
gathers the costs: it asks the gas estimator, the swap provider and (only
when the chains differ) the bridge, then hands the result to the cost engine
and stamps an expiry on it.

THE CIRCULARITY, AND HOW IT IS RESOLVED
To quote a swap you need an amount. The amount is what remains after costs.
One of the costs -- the slippage reserve -- only exists once the swap has
been quoted. That is a genuine loop, and the tempting fixes are both wrong:
quoting at the full ceiling overstates the purchase, and iterating to a
fixed point can spin.

So: price once with the costs that are knowable up front (gas, bridge, fee)
to get a provisional purchase, quote the swap at that amount, then re-price
with the reserve included. That second pass can only shrink the purchase, so
it terminates. If the shrunken purchase no longer fits, the quote is refused
rather than re-quoted again -- a third pass would be chasing a moving number
with the user's money.

The re-quote is deliberately NOT performed at the smaller amount. The
reserve is proportional, so the smaller trade's reserve is smaller too, and
using the larger reserve is the conservative direction: the ceiling holds
with room to spare rather than by a hair.

PARALLELISM
Gas, the bridge quote and the token price are independent of each other and
are fetched at the same time. The swap quote is not -- it needs the amount
those produce -- so it runs after them. Pretending otherwise would just mean
quoting the wrong amount faster.

Nothing here signs or broadcasts.
"""
from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_UP
from typing import Callable, Optional

from . import registry as R
from .costs import (
    CostLine, CostError, Quote, money, price_trade, sponsored_gas, ZERO,
    KIND_BRIDGE_FEE, KIND_DEST_GAS, KIND_SOURCE_GAS,
)
from .providers import ProviderError, SwapQuote, costs_from_swap_quote

# A quote is a promise about prices that move. Long enough to read the
# breakdown and press a button; short enough that the numbers are still
# true when it is used.
QUOTE_TTL_SECONDS = 30


class QuoteError(Exception):
    """No quote could be produced. Never a partially-filled one."""


@dataclass(frozen=True)
class QuoteRequest:
    user_id: int
    wallet: str
    source_chain: str
    destination_chain: str
    token_address: str
    max_spend_usd: Decimal
    taker_address: str
    slippage_bps: int = 100
    mode: str = 'manual'          # 'manual' | 'bot' | 'copy'

    def __post_init__(self):
        if isinstance(self.max_spend_usd, float):
            raise QuoteError('max_spend_usd must not be a float')
        if not self.token_address:
            raise QuoteError('no destination token given')
        if self.mode not in ('manual', 'bot', 'copy'):
            raise QuoteError(f'unknown trade mode {self.mode!r}')


@dataclass
class PricedQuote:
    """Everything the buy panel and the execute endpoint both need."""
    quote_id: str
    request: QuoteRequest
    priced: Quote
    swap: Optional[SwapQuote]
    route: str
    same_chain: bool
    created_at: float
    expires_at: float
    timings_ms: dict = field(default_factory=dict)
    warnings: tuple = ()

    def is_expired(self, now: Optional[float] = None) -> bool:
        return (now if now is not None else time.time()) >= self.expires_at

    def seconds_left(self, now: Optional[float] = None) -> float:
        return max(0.0, self.expires_at - (now if now is not None else time.time()))

    def to_dict(self, now: Optional[float] = None) -> dict:
        body = self.priced.breakdown()
        body.update({
            'quote_id': self.quote_id,
            'route': self.route,
            'same_chain': self.same_chain,
            'source_chain': self.request.source_chain,
            'destination_chain': self.request.destination_chain,
            'token_address': self.request.token_address,
            'mode': self.request.mode,
            'expires_in_seconds': round(self.seconds_left(now), 1),
            'expired': self.is_expired(now),
            'timings_ms': self.timings_ms,
            'warnings': list(self.warnings),
        })
        if self.swap is not None:
            body['expected_output_raw'] = str(self.swap.buy_amount_raw)
            body['minimum_output_raw'] = str(self.swap.min_buy_amount_raw)
            body['price_impact_pct'] = str(self.swap.price_impact_pct)
            body['swap_provider'] = self.swap.provider
        # An expired quote can never report itself as executable, whatever
        # the numbers said when it was made.
        if body['expired']:
            body['can_execute'] = False
            body['reject_reason'] = 'This quote has expired. Request a new one.'
        return body


def build_quote(
    req: QuoteRequest,
    *,
    swap_provider,
    gas_estimator: Callable,          # (chain) -> Decimal USD
    fee_rate,
    bridge_quoter: Optional[Callable] = None,   # (src, dst, usd) -> dict
    gas_is_sponsored: Callable = lambda chain: False,
    gas_from_native: Optional[Callable] = None,   # (chain, native amount) -> USD
    clock: Callable = time.time,
) -> PricedQuote:
    """Price a trade end to end. Raises rather than returning a half-quote."""
    started = clock()
    timings: dict = {}
    warnings: list = []

    src = R.get_chain(req.source_chain)
    dst = R.get_chain(req.destination_chain)
    same_chain = R.is_same_chain(req.source_chain, req.destination_chain)
    ceiling = money(req.max_spend_usd)
    if ceiling <= ZERO:
        raise QuoteError('maximum spend must be greater than zero')

    # ── independent lookups, at the same time ──
    t0 = clock()
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_src_gas = pool.submit(gas_estimator, src.name)
        f_dst_gas = pool.submit(gas_estimator, dst.name) if not same_chain else None
        f_bridge = (pool.submit(bridge_quoter, src.name, dst.name, ceiling)
                    if (not same_chain and bridge_quoter) else None)

        try:
            src_gas_usd = money(f_src_gas.result())
        except Exception as e:
            raise QuoteError(f'could not estimate gas on {src.name}: {e}') from e

        dst_gas_usd = ZERO
        if f_dst_gas is not None:
            try:
                dst_gas_usd = money(f_dst_gas.result())
            except Exception as e:
                raise QuoteError(f'could not estimate gas on {dst.name}: {e}') from e

        bridge_usd = ZERO
        if f_bridge is not None:
            try:
                bridge_usd = money((f_bridge.result() or {}).get('fee_usd', 0))
            except Exception as e:
                raise QuoteError(f'no bridge route {src.name} -> {dst.name}: {e}') from e
        elif not same_chain:
            raise QuoteError(
                f'{src.name} -> {dst.name} needs a bridge and none is configured'
            )
    timings['lookups_ms'] = round((clock() - t0) * 1000, 1)

    # ── costs that are knowable before the swap is quoted ──
    upfront = []
    if src_gas_usd > ZERO:
        # Sponsored gas is charged to the user's budget, which is what makes
        # the sponsor a payment rail rather than a subsidy. When it cannot be
        # recovered the cost engine refuses the quote — see costs.py.
        upfront.append(
            sponsored_gas(src_gas_usd, recovered=True,
                          detail=f'{src.native.symbol} on {src.display_name}, '
                                 f'fronted by the sponsor wallet')
            if gas_is_sponsored(src.name) else
            CostLine(KIND_SOURCE_GAS, src_gas_usd, source='rpc',
                     detail=f'{src.native.symbol} on {src.display_name}')
        )
    if dst_gas_usd > ZERO:
        upfront.append(CostLine(KIND_DEST_GAS, dst_gas_usd, source='rpc',
                                detail=f'{dst.native.symbol} on {dst.display_name}'))
    if bridge_usd > ZERO:
        upfront.append(CostLine(KIND_BRIDGE_FEE, bridge_usd, source='bridge'))

    # ── pass one: what is provisionally left to spend ──
    provisional = price_trade(ceiling, fee_rate, upfront, same_chain=same_chain)
    if provisional.token_purchase_usd <= ZERO:
        return PricedQuote(
            quote_id=uuid.uuid4().hex, request=req, priced=provisional, swap=None,
            route=f'{src.name}->{dst.name}', same_chain=same_chain,
            created_at=started, expires_at=started + QUOTE_TTL_SECONDS,
            timings_ms=timings,
            warnings=('costs use up the whole budget before any swap is quoted',),
        )

    # ── the swap, at that provisional amount ──
    t1 = clock()
    stable = src.stable
    try:
        sell_raw = R.to_raw(provisional.token_purchase_usd, stable)
    except R.UnknownDecimals as e:
        raise QuoteError(str(e)) from e
    try:
        swap = swap_provider.quote(
            chain=dst.name, sell_asset=stable, buy_address=req.token_address,
            sell_amount_raw=sell_raw, taker=req.taker_address,
        )
    except ProviderError as e:
        raise QuoteError(str(e)) from e
    timings['swap_quote_ms'] = round((clock() - t1) * 1000, 1)

    # ── pass two: add the reserve the swap revealed, and re-price ──
    try:
        reserve_lines = costs_from_swap_quote(swap)
    except ProviderError as e:
        raise QuoteError(str(e)) from e

    # The swap quote knows what THIS route costs in gas. The estimate used in
    # pass one could not -- there was no route yet -- so it comes from a
    # conservative constant sized to fund a wallet for a worst-case
    # approve-plus-swap, which is the right number to top someone up with and
    # far too large to price a trade with. On a small trade the difference is
    # the difference between a sensible cost and half the order.
    #
    # Only ever replaces the source-gas line, and only when the provider
    # actually reported one; an unreadable figure stays unknown rather than
    # becoming a cheaper guess.
    if gas_from_native is not None and getattr(swap, 'estimated_gas_native', None):
        try:
            # Quantised to the cent, rounding UP: a cost is never understated,
            # and a breakdown that reads "0.4000" is not a currency figure.
            real_gas = money(gas_from_native(src.name, swap.estimated_gas_native)
                             ).quantize(Decimal('0.01'), rounding=ROUND_UP)
        except Exception as e:
            real_gas = None
            warnings.append(f'could not price the route\'s own gas estimate ({e}); '
                            f'using the conservative one')
        if real_gas is not None and real_gas > ZERO:
            upfront = [c for c in upfront if c.kind != KIND_SOURCE_GAS] + [
                sponsored_gas(real_gas, recovered=True,
                              detail=f'{src.native.symbol} on {src.display_name}, '
                                     f'fronted by the sponsor wallet')
                if gas_is_sponsored(src.name) else
                CostLine(KIND_SOURCE_GAS, real_gas, source='0x',
                         detail=f'{src.native.symbol} on {src.display_name}, '
                                f'estimated for this route')
            ]

    final = price_trade(ceiling, fee_rate, upfront + reserve_lines, same_chain=same_chain)

    if final.token_purchase_usd < provisional.token_purchase_usd:
        # Expected: the reserve took a bite. The swap was quoted at the
        # larger amount, so its reserve is the conservative one — the real
        # trade needs less. Recorded rather than re-quoted, because a third
        # pass chases a number that keeps moving.
        warnings.append(
            f'priced against a slippage reserve quoted at '
            f'${provisional.token_purchase_usd}; the executed amount of '
            f'${final.token_purchase_usd} needs no more than that'
        )
    if not final.can_execute and final.reject_reason:
        warnings.append(final.reject_reason)

    timings['total_ms'] = round((clock() - started) * 1000, 1)
    return PricedQuote(
        quote_id=uuid.uuid4().hex,
        request=req,
        priced=final,
        swap=swap,
        route=(f'{src.name} {stable.symbol} -> {swap.provider}'
               if same_chain else
               f'{src.name} {stable.symbol} -> bridge -> {dst.name} -> {swap.provider}'),
        same_chain=same_chain,
        created_at=started,
        expires_at=started + QUOTE_TTL_SECONDS,
        timings_ms=timings,
        warnings=tuple(warnings),
    )
