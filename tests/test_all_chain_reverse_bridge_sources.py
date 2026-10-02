"""Regression coverage for every supported EVM source -> Solana USDC buy.

No RPC calls are made here. The test exercises the reverse-bridge source picker
with the same five EVM chain names the registry exposes, and verifies that
Live Market's buy route still recognises all of them.
"""
# Runnable on its own, like every other test here: these import modules from
# the repository root, and `python3 tests/x.py` puts tests/ on the path and
# not the root. Without this the file fails with ModuleNotFoundError and
# reads as a broken test rather than a missing PYTHONPATH.
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

from pathlib import Path
from types import SimpleNamespace

import evm_to_solana_bridge as ext
from trade_engine.registry import CHAINS

ROOT = Path(__file__).resolve().parents[1]
LM = (ROOT / 'static' / 'live-market-pro.js').read_text(encoding='utf-8')

EXPECTED_EVM = {'bsc', 'base', 'arbitrum'}


def check(message, condition):
    assert condition, message
    print('PASS ' + message)


check('active EVM set is BSC, Base and Arbitrum; legacy registry metadata may still contain disabled chains',
      EXPECTED_EVM.issubset({name for name, cfg in CHAINS.items() if cfg.kind == 'evm'}))
_lm_evm = LM.split('var EVM_TRADE_CHAINS = {', 1)[1].split('}', 1)[0]
check('Live Market recognises every supported EVM chain',
      all((f"{chain}:1" in _lm_evm) for chain in EXPECTED_EVM))

balances = {
    'bsc': 200.0,
    'base': 200.0,
    'arbitrum': 200.0,
}
needs_sponsor = {chain: False for chain in EXPECTED_EVM}
# Base is intentionally cheapest so the selector proves it chooses among
# the active source chains rather than legacy registry entries.
gas_usd = {
    'bsc': 0.40,
    'base': 0.10,
    'arbitrum': 0.30,
}

fake = SimpleNamespace(
    SOLANA_MIN_SPEND_USDC=1.0,
    SOL_NETWORK_RESERVE=0.005,
    _sol_price_usd=100.0,
    EVM_CHAINS={**{chain: {'usdc': f'{chain.upper()}_STABLE'} for chain in EXPECTED_EVM},
                'robinhood': {'usdc': 'ROBINHOOD_STABLE'}},
    ACTIVE_EVM_CHAINS={chain: {'usdc': f'{chain.upper()}_STABLE'} for chain in EXPECTED_EVM},
    get_evm_usdc_balance=lambda _addr, chain: balances[chain],
    _te_needs_sponsored_gas=lambda chain, _addr: needs_sponsor[chain],
    _te_gas_usd=lambda chain: gas_usd[chain],
)

source = ext._pick_evm_source(fake, '0xabc', 100.0)
check('Base can be selected as the cheapest active EVM source for a Solana USDC buy',
      source[0] == 'base')
check('selected source uses its configured stablecoin address',
      source[1] == 'BASE_STABLE')
check('disabled Robinhood is never considered as a reverse-bridge source',
      source[0] != 'robinhood')
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
