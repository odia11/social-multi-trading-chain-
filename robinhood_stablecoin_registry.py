"""Resolve Robinhood Chain's trading stablecoin by ASKING THE CONTRACT.

Robinhood Chain does not use USDC. The asset the engine settles in there is
Global Dollar (USDG) at 0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168, and
``trade_engine.registry`` deliberately carries it with decimals=None -- which
makes every Robinhood route refuse, because require_decimals() raises rather
than guess. That is correct and it is also a dead end: a perfectly good
USDC -> USDG -> token route never reaches 0x.

HOW THAT GAP IS MEANT TO BE CLOSED
The registry says so itself, in verify_decimals():

    "This is how that gap is closed properly: by the app reading decimals()
     on-chain and telling the registry the answer, rather than by somebody
     typing a plausible number into this file."

So this reads decimals() from the deployed contract. USDG is 6 decimals
everywhere Paxos has issued it, and that expectation is kept here -- not as
the answer, but as a CROSS-CHECK. If Robinhood Chain's deployment answers
anything else, this refuses rather than resize every trade on that chain by a
factor of ten to the something.

WHEN THE CHAIN CANNOT BE REACHED
Nothing is installed and decimals stay None: Robinhood routes keep refusing
until a later startup can actually ask. An RPC that is down is not evidence
about a token's decimals, and a plausible default is exactly the failure this
whole mechanism exists to prevent.

An 18-decimal stablecoin read as 6 is a 10^12 sizing error. BSC's own USDC is
18 while everyone else's is 6, which is why nobody gets to assume.
"""
from __future__ import annotations


ROBINHOOD_USDG = '0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168'

# What Paxos issues USDG with elsewhere. A cross-check, never the source.
ROBINHOOD_USDG_DECIMALS = 6

_DECIMALS_ABI = [{
    'constant': True, 'inputs': [], 'name': 'decimals',
    'outputs': [{'name': '', 'type': 'uint8'}],
    'payable': False, 'stateMutability': 'view', 'type': 'function',
}]


class RobinhoodStablecoinMismatch(RuntimeError):
    """The registry, or the chain, is not what this adapter was written for."""


def read_onchain_decimals(d) -> int | None:
    """decimals() from the deployed USDG contract, or None if unreachable.

    None is a real answer here and it means "we do not know", which is the
    one thing this must never quietly turn into a number.
    """
    try:
        w3 = d._get_web3('robinhood')
        contract = w3.eth.contract(
            address=w3.to_checksum_address(ROBINHOOD_USDG), abi=_DECIMALS_ABI)
        return int(contract.functions.decimals().call())
    except Exception as e:
        print(f'[robinhood] could not read USDG decimals on chain: '
              f'{type(e).__name__}: {e}', flush=True)
        return None


def install(d):
    """Verify USDG's decimals against the chain and record them.

    Raises RobinhoodStablecoinMismatch (a RuntimeError) when the registry is
    not the deployment this was written for, or when the chain contradicts
    the expected value. The caller decides what a mismatch costs -- app_entry
    logs it and carries on, because Robinhood metadata must not be able to
    stop Solana trading.
    """
    registry = d.te_registry
    chain = registry.get_chain('robinhood')

    if chain.stable.address.lower() != ROBINHOOD_USDG.lower():
        raise RobinhoodStablecoinMismatch(
            'Robinhood stablecoin registry changed; refusing to apply USDG metadata '
            f'to unexpected address {chain.stable.address}'
        )
    if chain.stable.symbol != 'USDG':
        raise RobinhoodStablecoinMismatch(
            'Robinhood stablecoin registry is not USDG; refusing to continue with '
            f'unexpected symbol {chain.stable.symbol!r}'
        )

    if chain.stable.decimals is not None:
        return chain.stable          # already verified; nothing to do

    onchain = read_onchain_decimals(d)
    if onchain is None:
        # Fail closed, loudly. Robinhood routes keep refusing; every other
        # chain is unaffected.
        print('[robinhood] USDG decimals stay unverified — Robinhood routes '
              'will keep refusing until the chain can be asked', flush=True)
        return None

    if onchain != ROBINHOOD_USDG_DECIMALS:
        raise RobinhoodStablecoinMismatch(
            f'Robinhood USDG reports {onchain} decimals on chain, not the '
            f'{ROBINHOOD_USDG_DECIMALS} this adapter expects. Refusing to size '
            f'trades against either number until a person has looked.'
        )

    asset = registry.verify_decimals(
        'robinhood', ROBINHOOD_USDG, onchain,
        source='decimals() on the deployed Robinhood Chain USDG contract')
    print(f'[robinhood] USDG verified at {onchain} decimals, read from the '
          f'contract', flush=True)
    return asset
