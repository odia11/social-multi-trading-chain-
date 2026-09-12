"""Regression coverage for every supported EVM source -> Solana USDC buy.

No RPC calls are made here. The test exercises the reverse-bridge source picker
with the same five EVM chain names the registry exposes, and verifies that the
frontend's shared token-card route still recognises all of them.
"""
from pathlib import Path
from types import SimpleNamespace

import evm_to_solana_bridge as ext
from trade_engine.registry import CHAINS

ROOT = Path(__file__).resolve().parents[1]
CARD = (ROOT / 'static' / 'token-card.js').read_text(encoding='utf-8')

EXPECTED_EVM = {'bsc', 'base', 'arbitrum', 'polygon', 'robinhood'}


def check(message, condition):
    assert condition, message
    print('PASS ' + message)


check('registry exposes exactly the five supported EVM chains',
      {name for name, cfg in CHAINS.items() if cfg.kind == 'evm'} == EXPECTED_EVM)
check('frontend token card recognises every supported EVM chain',
      all((f"'{chain}'" in CARD) for chain in EXPECTED_EVM))

balances = {
    'bsc': 200.0,
    'base': 200.0,
    'arbitrum': 200.0,
    'polygon': 200.0,
    'robinhood': 200.0,
}
needs_sponsor = {chain: False for chain in EXPECTED_EVM}
# Robinhood is intentionally cheapest so this proves it is a real candidate,
# not merely present in a UI list. Its dashboard `usdc` slot represents the
# chain's configured dollar stablecoin; 0x handles the cross-chain conversion
# to the real Solana USDC mint.
gas_usd = {
    'bsc': 0.40,
    'base': 0.25,
    'arbitrum': 0.30,
    'polygon': 0.20,
    'robinhood': 0.10,
}

fake = SimpleNamespace(
    SOLANA_MIN_SPEND_USDC=1.0,
    SOL_NETWORK_RESERVE=0.005,
    _sol_price_usd=100.0,
    EVM_CHAINS={chain: {'usdc': f'{chain.upper()}_STABLE'} for chain in EXPECTED_EVM},
    get_evm_usdc_balance=lambda _addr, chain: balances[chain],
    _te_needs_sponsored_gas=lambda chain, _addr: needs_sponsor[chain],
    _te_gas_usd=lambda chain: gas_usd[chain],
)

source = ext._pick_evm_source(fake, '0xabc', 100.0)
check('Robinhood can be selected as an EVM source for a Solana USDC buy',
      source[0] == 'robinhood')
check('selected source uses its configured stablecoin address',
      source[1] == 'ROBINHOOD_STABLE')
check('all planned network cost stays inside the user-entered ceiling',
      abs(source[3] + source[4] + source[5] - 100.0) < 1e-9)

# Force each chain to be the only viable source once. This catches accidental
# filtering of any single chain in the selector.
for wanted in sorted(EXPECTED_EVM):
    for chain in EXPECTED_EVM:
        needs_sponsor[chain] = chain != wanted
    picked = ext._pick_evm_source(fake, '0xabc', 100.0)
    check(f'{wanted} remains a valid reverse-bridge source',
          picked is not None and picked[0] == wanted)

print('\n10/10 checks passed')
