from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

dash = (ROOT / 'dashboard.py').read_text()
wallet = (ROOT / 'templates' / 'wallet.html').read_text()
navbar = (ROOT / 'static' / 'navbar.js').read_text()
market = (ROOT / 'static' / 'live-market-pro.js').read_text()
header = (ROOT / 'header_stable_balance.py').read_text()
portfolio = (ROOT / 'portfolio_multichain_holdings.py').read_text()
pooled = (ROOT / 'live_market_pooled_buy_balance.py').read_text()

assert "DISABLED_EVM_CHAINS = frozenset({'robinhood'})" in dash
assert "ACTIVE_EVM_CHAINS = {k: v for k, v in EVM_CHAINS.items()" in dash
assert "_MARKET_LIVE_CHAINS = {'solana', 'bsc', 'base', 'arbitrum'}" in dash
assert "_CALL_LOOKUP_EVM_CHAINS = ('base', 'bsc', 'arbitrum')" in dash
assert "for _evm_chain in ACTIVE_EVM_CHAINS:" in dash
assert "for _bc, _bcfg in ACTIVE_EVM_CHAINS.items():" in dash

# Defense in depth: even a stale/internal caller must be stopped before 0x.
quote_guard = "if chain not in ACTIVE_EVM_CHAINS:\n        raise RuntimeError(f'{chain} trading is temporarily disabled on OrcAgent')"
assert quote_guard in dash
assert dash.index(quote_guard) < dash.index("'https://api.0x.org/swap/allowance-holder/quote'")

# No new user-facing Robinhood actions.
assert 'value="robinhood"' not in wallet
assert "{v:'robinhood'" not in wallet
assert "_NB_LIVE_CHAINS=['solana','bsc','base','arbitrum'];" in navbar
assert "var EVM_TRADE_CHAINS = {bsc:1, base:1, arbitrum:1};" in market
assert "_CHAINS = ('bsc', 'base', 'arbitrum')" in header
assert "var CHAINS = ['bsc','base','arbitrum'];" in pooled

# Portfolio/balance polling follows active chains, while legacy config may
# remain readable for old transaction/history rows.
assert "getattr(d, 'ACTIVE_EVM_CHAINS', {})" in portfolio
assert "for chain in ACTIVE_EVM_CHAINS:" in dash

print('PASS Robinhood is soft-disabled: history compatible, no new discovery/quotes/trades/bridges/UI actions')
