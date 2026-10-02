"""Legacy Robinhood/EVM support stays disabled under the Solana-only product."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
dash=(ROOT/'dashboard.py').read_text()
wallet=(ROOT/'templates'/'wallet.html').read_text()
navbar=(ROOT/'static'/'navbar.js').read_text()
market=(ROOT/'static'/'live-market-pro.js').read_text()
entry=(ROOT/'app_entry.py').read_text()

assert 'DISABLED_EVM_CHAINS = frozenset(EVM_CHAINS)' in dash
assert 'ACTIVE_EVM_CHAINS = {}' in dash
assert "_MARKET_LIVE_CHAINS = {'solana'}" in dash
assert "_CALL_LOOKUP_EVM_CHAINS = ()" in dash
assert "_NB_LIVE_CHAINS=['solana'];" in navbar
assert 'EVM_TRADE_CHAINS' not in market
assert '/api/bsc/trade/' not in market and '/api/evm/trade/' not in market
assert 'value="robinhood"' not in wallet
for mod in ('bsc_gasless_trading','sponsored_gas','evm_to_solana_bridge','multichain_auto_bot'):
    assert mod not in entry
print('PASS Robinhood and every EVM chain are inactive; OrcAgent is Solana-only')
