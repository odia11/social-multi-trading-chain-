"""Turning a provider's answer into costs the engine can reason about.

WHY ADAPTERS AND NOT A REWRITE
The app already talks to 0x and Jupiter, and those integrations work. This
does not replace them -- each adapter takes a callable that performs the
real request (dashboard's own _get_0x_quote, orcagent_solana's Jupiter
call) and only normalises what comes back. That keeps one implementation of
each integration and makes the engine testable without a network, because a
test passes a function that returns a recorded response.

THE JOB IS NORMALISATION, AND THE RISK IS DOUBLE COUNTING
Providers disagree about what a "fee" is. A 0x quote already has its router
fee and price impact priced into the amount it promises to deliver; adding a
separately estimated router fee on top charges the user twice for one thing.
So each adapter states which costs its quote ALREADY includes, and the
engine only adds costs nobody has accounted for yet. Everything carries the
provider name so the breakdown shows where each figure came from.

Nothing here signs, sends, or broadcasts. Quoting only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Optional

from .costs import (
    CostError, CostLine, money, KIND_DEX_FEE, KIND_SLIPPAGE_RESERVE, ZERO,
)
from . import registry as R


class ProviderError(Exception):
    """A provider could not answer. Never a reason to guess a number."""


@dataclass
class SwapQuote:
    """What a DEX aggregator promises, normalised.

    `included_kinds` is the important field: the costs this quote has
    already priced in, which the engine must therefore not add again.
    """
    provider: str
    chain: str
    sell_asset: R.Asset
    buy_address: str
    sell_amount_raw: int
    buy_amount_raw: int
    min_buy_amount_raw: int          # after slippage tolerance
    price_impact_pct: Decimal
    estimated_gas_native: Optional[Decimal]
    included_kinds: frozenset = field(default_factory=frozenset)
    raw: dict = field(default_factory=dict)

    @property
    def slippage_reserve_raw(self) -> int:
        """The gap between promised and guaranteed output.

        This is a RESERVE, not a fee: it is the worst case, and whatever is
        not used comes back. Treating it as a certain cost would shrink
        every purchase by an amount the user usually never pays.
        """
        return max(0, self.buy_amount_raw - self.min_buy_amount_raw)


class SwapProvider:
    """One integration. Subclasses only translate; they never call out."""
    name = 'abstract'

    def quote(self, *, chain, sell_asset, buy_address, sell_amount_raw, taker) -> SwapQuote:
        raise NotImplementedError


class ZeroExProvider(SwapProvider):
    """0x Swap API v2, as the app already calls it.

    `fetch` is dashboard's _get_0x_quote (or anything with its signature),
    injected rather than imported so this module stays free of the app and
    a test can hand it a recorded response.
    """
    name = '0x'

    def __init__(self, fetch: Callable):
        self._fetch = fetch

    def quote(self, *, chain, sell_asset, buy_address, sell_amount_raw, taker) -> SwapQuote:
        chain_cfg = R.get_chain(chain)
        if chain_cfg.kind != 'evm':
            raise ProviderError(f'0x does not serve {chain}, which is not EVM')
        try:
            data = self._fetch(sell_asset.address, buy_address, int(sell_amount_raw),
                               taker, chain)
        except Exception as e:
            raise ProviderError(f'0x quote failed on {chain}: {e}') from e
        if not isinstance(data, dict):
            raise ProviderError('0x returned a non-object response')

        buy_amount = data.get('buyAmount')
        min_buy = data.get('minBuyAmount') or buy_amount
        if buy_amount in (None, ''):
            raise ProviderError('0x quote has no buyAmount — treating as no route '
                                'rather than assuming zero')

        gas_native = None
        try:
            gas_units = data.get('gas') or (data.get('transaction') or {}).get('gas')
            gas_price = data.get('gasPrice') or (data.get('transaction') or {}).get('gasPrice')
            if gas_units and gas_price:
                gas_native = (Decimal(str(gas_units)) * Decimal(str(gas_price))
                              / Decimal(10) ** 18)
        except Exception:
            gas_native = None      # an unreadable gas figure is unknown, not zero

        return SwapQuote(
            provider=self.name,
            chain=chain,
            sell_asset=sell_asset,
            buy_address=buy_address,
            sell_amount_raw=int(sell_amount_raw),
            buy_amount_raw=int(buy_amount),
            min_buy_amount_raw=int(min_buy),
            price_impact_pct=money(data.get('estimatedPriceImpact') or '0'),
            estimated_gas_native=gas_native,
            # 0x prices its router and liquidity-provider fees into buyAmount.
            # Adding a separate router cost here would bill the user twice.
            included_kinds=frozenset({KIND_DEX_FEE}),
            raw=data,
        )


class JupiterProvider(SwapProvider):
    """Jupiter, as orcagent_solana.py already calls it.

    Solana has no gas price in the EVM sense; the network fee plus priority
    fee is small and near-constant, and the existing swap path already
    handles it. So this reports no gas estimate rather than inventing one,
    and the engine sources Solana gas separately.
    """
    name = 'jupiter'

    def __init__(self, fetch: Callable):
        self._fetch = fetch

    def quote(self, *, chain, sell_asset, buy_address, sell_amount_raw, taker) -> SwapQuote:
        if R.get_chain(chain).kind != 'svm':
            raise ProviderError(f'Jupiter does not serve {chain}')
        try:
            data = self._fetch(sell_asset.address, buy_address, int(sell_amount_raw))
        except Exception as e:
            raise ProviderError(f'Jupiter quote failed: {e}') from e
        if not isinstance(data, dict):
            raise ProviderError('Jupiter returned a non-object response')

        out = data.get('outAmount')
        if out in (None, ''):
            raise ProviderError('Jupiter quote has no outAmount — no route')
        other = data.get('otherAmountThreshold') or out

        return SwapQuote(
            provider=self.name,
            chain=chain,
            sell_asset=sell_asset,
            buy_address=buy_address,
            sell_amount_raw=int(sell_amount_raw),
            buy_amount_raw=int(out),
            min_buy_amount_raw=int(other),
            price_impact_pct=money(data.get('priceImpactPct') or '0') * 100,
            estimated_gas_native=None,
            included_kinds=frozenset({KIND_DEX_FEE}),
            raw=data,
        )


def costs_from_swap_quote(q: SwapQuote, *, stable_price_usd=Decimal('1')) -> list:
    """The costs a swap quote implies, minus the ones it already covers.

    Only the slippage reserve is returned today, and only because the
    aggregators do NOT price it in -- it is the difference between what they
    expect to deliver and what they guarantee. The DEX fee is deliberately
    absent: both providers have it inside their output amount, and this is
    the exact place a second charge for it would creep in.
    """
    lines = []
    if KIND_DEX_FEE not in q.included_kinds:
        raise ProviderError(
            f'{q.provider} does not state whether its DEX fee is included; '
            f'refusing to guess rather than risk charging it twice'
        )
    reserve_raw = q.slippage_reserve_raw
    if reserve_raw > 0:
        # Valued in the SELL asset, which is the dollar stable the trade is
        # funded with -- so the reserve is expressed in the same currency as
        # the ceiling it has to fit inside.
        fraction = Decimal(reserve_raw) / Decimal(q.buy_amount_raw or 1)
        sell_units = R.from_raw(q.sell_amount_raw, q.sell_asset)
        lines.append(CostLine(
            kind=KIND_SLIPPAGE_RESERVE,
            usd=(sell_units * fraction * money(stable_price_usd)).quantize(Decimal('0.01')),
            source=q.provider,
            detail='worst case under the quoted slippage tolerance; released if unused',
        ))
    return lines
