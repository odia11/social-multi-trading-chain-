"""Pin the canonical Robinhood Chain trading stablecoin metadata at startup.

Robinhood Chain does not use USDC as OrcAgent's local settlement stablecoin.
The canonical asset used by the trading engine is Global Dollar (USDG) at
0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168, and that deployed token has
6 decimals.

Why this startup adapter exists instead of silently assuming 6 in the bridge
math: ``trade_engine.registry`` deliberately leaves unknown decimals as None.
That is normally the safe choice, but the cross-chain engine calls
``Asset.require_decimals()`` while comparing source amount with destination
minimum output. With Robinhood USDG left unresolved, a perfectly valid
USDC -> USDG -> token route dies before 0x can execute it.

The address and value below are explicit and fail closed. If the registry is
changed to a different Robinhood stablecoin, startup refuses to overwrite it.
"""
from __future__ import annotations


ROBINHOOD_USDG = '0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168'
ROBINHOOD_USDG_DECIMALS = 6


def install(d):
    registry = d.te_registry
    chain = registry.get_chain('robinhood')

    if chain.stable.address.lower() != ROBINHOOD_USDG.lower():
        raise RuntimeError(
            'Robinhood stablecoin registry changed; refusing to apply USDG metadata '
            f'to unexpected address {chain.stable.address}'
        )

    if chain.stable.symbol != 'USDG':
        raise RuntimeError(
            'Robinhood stablecoin registry is not USDG; refusing to continue with '
            f'unexpected symbol {chain.stable.symbol!r}'
        )

    # verify_decimals only fills a blank or confirms the exact existing value.
    # A conflicting value raises RegistryError instead of resizing trades.
    registry.verify_decimals(
        'robinhood',
        ROBINHOOD_USDG,
        ROBINHOOD_USDG_DECIMALS,
        source='canonical Robinhood Chain USDG mainnet contract',
    )
