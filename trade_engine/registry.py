"""Which chains and assets exist, and what their real decimals are.

WHY THIS EXISTS
Today a token is identified by symbol in several places -- and symbols are
not unique. "USDT on Ethereum" and "USDT on BSC" are two entirely separate
on-chain assets that happen to print the same five characters, and a search
for the ticker "D" returns dozens of different coins. Everything here is
keyed on (chain, address), never on a symbol, so that class of mistake
cannot be expressed.

DECIMALS ARE NOT ASSUMED
The single most expensive assumption available here is that a dollar
stablecoin has 6 decimals. Binance-Peg USDC on BSC has 18. Getting that
wrong by a factor of 10^12 does not raise -- it silently spends a millionth
of what was intended, or a trillion times more. So a decimals value is
recorded here ONLY where it has been verified against the deployed contract;
anything else is None, and asking for it raises rather than guessing. The
app already reads decimals() from the contract at swap time (see
_execute_evm_swap in dashboard.py), which is the correct fallback.

This module is pure data and pure functions. It opens no connection, reads
no environment, and imports nothing from the app -- so it can be used from
the engine, from a test, or from a script without starting anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class RegistryError(Exception):
    """Raised instead of returning a plausible-looking wrong answer."""


class UnknownDecimals(RegistryError):
    """The decimals for this asset have not been verified.

    Deliberately fatal. The caller must read decimals() from the contract
    rather than fall back to a default, because every available default is
    wrong for at least one asset the platform already trades.
    """


@dataclass(frozen=True)
class Asset:
    """One asset on one chain. `address` is a contract address on EVM and a
    mint address on Solana; the two namespaces never mix because the chain
    is part of the key."""
    chain: str
    address: str
    symbol: str
    decimals: Optional[int]      # None = never verified, must be read on-chain
    kind: str                    # 'native' | 'stable' | 'token'
    note: str = ''

    @property
    def key(self) -> tuple:
        return (self.chain, self.address.lower())

    def require_decimals(self) -> int:
        if self.decimals is None:
            raise UnknownDecimals(
                f'{self.symbol} on {self.chain} ({self.address}) has no verified '
                f'decimals in the registry — read decimals() from the contract '
                f'instead of assuming a default'
            )
        return self.decimals


@dataclass(frozen=True)
class Chain:
    """A chain the platform already trades. `chain_id` is None for Solana,
    which has no EVM chain id -- that absence is meaningful, not missing
    data, so it is not faked with a sentinel number."""
    name: str
    kind: str                    # 'evm' | 'svm'
    chain_id: Optional[int]
    native: Asset
    stable: Asset                # the dollar asset trades are funded with
    swap_provider: str           # which integration executes a swap here
    display_name: str


def _evm(chain: str, address: str, symbol: str, decimals: Optional[int],
         kind: str, note: str = '') -> Asset:
    return Asset(chain=chain, address=address, symbol=symbol,
                 decimals=decimals, kind=kind, note=note)


# ── Solana ───────────────────────────────────────────────────────────────
_SOL = _evm('solana', 'So11111111111111111111111111111111111111112', 'SOL', 9, 'native')
_SOL_USDC = _evm('solana', 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v', 'USDC', 6, 'stable')

# ── EVM ──────────────────────────────────────────────────────────────────
# Native decimals are 18 on every EVM chain the platform trades. The stable
# decimals are the ones that differ, and BSC is the reason this file exists.
_BSC_BNB = _evm('bsc', '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE', 'BNB', 18, 'native')
_BSC_USDC = _evm(
    'bsc', '0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d', 'USDC', 18, 'stable',
    note='Binance-Peg USDC is 18 decimals, NOT the 6 that USDC has everywhere else',
)

_BASE_ETH = _evm('base', '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE', 'ETH', 18, 'native')
_BASE_USDC = _evm('base', '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913', 'USDC', 6, 'stable')

_ARB_ETH = _evm('arbitrum', '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE', 'ETH', 18, 'native')
_ARB_USDC = _evm('arbitrum', '0xaf88d065e77c8cC2239327C5EDb3A432268e5831', 'USDC', 6, 'stable')

_POLY_POL = _evm('polygon', '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE', 'POL', 18, 'native')
_POLY_USDC = _evm('polygon', '0x3c499c542cef5e3811e1192ce70d8cc03d5c3359', 'USDC', 6, 'stable')

_HOOD_ETH = _evm('robinhood', '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE', 'ETH', 18, 'native')
# USDG, not USDC, and its decimals have not been verified against the
# deployed contract from here. Left as None on purpose: an unverified 6 that
# turns out to be 18 is a 10^12 sizing error, and this is the one asset in
# the set whose decimals nobody has confirmed.
_HOOD_USDG = _evm(
    'robinhood', '0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168', 'USDG', None, 'stable',
    note='Global Dollar, not USDC. Decimals unverified — read from the contract.',
)

CHAINS: dict = {
    'solana': Chain('solana', 'svm', None, _SOL, _SOL_USDC, 'jupiter', 'Solana'),
    'bsc': Chain('bsc', 'evm', 56, _BSC_BNB, _BSC_USDC, '0x', 'BNB Chain'),
    'base': Chain('base', 'evm', 8453, _BASE_ETH, _BASE_USDC, '0x', 'Base'),
    'arbitrum': Chain('arbitrum', 'evm', 42161, _ARB_ETH, _ARB_USDC, '0x', 'Arbitrum'),
    'polygon': Chain('polygon', 'evm', 137, _POLY_POL, _POLY_USDC, '0x', 'Polygon'),
    'robinhood': Chain('robinhood', 'evm', 4663, _HOOD_ETH, _HOOD_USDG, '0x', 'Robinhood Chain'),
}


def verify_decimals(chain: str, address: str, decimals: int,
                    source: str = 'contract') -> Asset:
    """Record decimals that were READ from the deployed contract.

    The registry refuses to guess -- an unverified 6 that turns out to be 18
    is a 10^12 sizing error -- so an asset it does not know stays None and
    raises. This is how that gap is closed properly: by the app reading
    decimals() on-chain and telling the registry the answer, rather than by
    somebody typing a plausible number into this file.

    Only ever fills a blank. An asset whose decimals are already known is not
    overwritten: a value that has been verified is not something a runtime
    lookup should be able to change, because that is how a wrong RPC answer
    would silently resize every trade on a chain.
    """
    if not isinstance(decimals, int) or isinstance(decimals, bool):
        raise RegistryError(f'decimals must be an int, got {decimals!r}')
    if not 0 <= decimals <= 36:
        raise RegistryError(f'{decimals} is not a plausible decimals value')

    ch = get_chain(chain)
    for field in ('native', 'stable'):
        asset = getattr(ch, field)
        if asset.address.lower() != (address or '').lower():
            continue
        if asset.decimals is not None:
            if asset.decimals != decimals:
                raise RegistryError(
                    f'{asset.symbol} on {chain} is recorded as {asset.decimals} '
                    f'decimals but the {source} says {decimals} — refusing to '
                    f'change a verified value at runtime'
                )
            return asset
        filled = Asset(chain=asset.chain, address=asset.address,
                       symbol=asset.symbol, decimals=decimals, kind=asset.kind,
                       note=(asset.note + f' [verified {decimals} from {source}]').strip())
        CHAINS[ch.name] = Chain(
            name=ch.name, kind=ch.kind, chain_id=ch.chain_id,
            native=filled if field == 'native' else ch.native,
            stable=filled if field == 'stable' else ch.stable,
            swap_provider=ch.swap_provider, display_name=ch.display_name)
        return filled
    raise RegistryError(f'{address} is not the native or stable asset of {chain}')


def unverified_assets() -> list:
    """Every asset whose decimals nobody has confirmed, so a caller can go and
    read them rather than discovering the gap mid-trade."""
    out = []
    for ch in CHAINS.values():
        for asset in (ch.native, ch.stable):
            if asset.decimals is None:
                out.append(asset)
    return out


def get_chain(name: str) -> Chain:
    chain = CHAINS.get((name or '').strip().lower())
    if chain is None:
        raise RegistryError(
            f'unsupported chain {name!r} — supported: {", ".join(sorted(CHAINS))}'
        )
    return chain


def is_same_chain(source: str, destination: str) -> bool:
    """Whether a trade can take the fast path and skip bridging entirely.

    Compared through get_chain so an unknown or misspelled chain raises here
    rather than quietly reading as 'different' and routing a same-chain
    trade across a bridge it never needed.
    """
    return get_chain(source).name == get_chain(destination).name


def to_raw(amount, asset: Asset) -> int:
    """Human amount -> integer base units, exactly.

    Takes a Decimal (or anything Decimal accepts) and never a float:
    int(0.1 * 10**18) is 99999999999999998, and that missing wei is the kind
    of error that only shows up in a reconciliation months later.
    """
    from decimal import Decimal
    if isinstance(amount, float):
        raise RegistryError(
            'refusing to convert a float to base units — pass a Decimal or a '
            'string, because binary floats cannot represent most decimal amounts'
        )
    scaled = Decimal(amount) * (10 ** asset.require_decimals())
    if scaled != scaled.to_integral_value():
        raise RegistryError(
            f'{amount} has more precision than {asset.symbol} can hold '
            f'({asset.decimals} decimals) — round it before converting'
        )
    return int(scaled)


def from_raw(raw: int, asset: Asset):
    """Integer base units -> Decimal human amount, exactly."""
    from decimal import Decimal
    return Decimal(int(raw)) / (10 ** asset.require_decimals())
