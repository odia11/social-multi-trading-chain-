"""Product contract: OrcAgent is Solana-only and cannot call 0x/EVM routes."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
dash = (ROOT / 'dashboard.py').read_text()
entry = (ROOT / 'app_entry.py').read_text()
wallet = (ROOT / 'templates' / 'wallet.html').read_text()
navbar = (ROOT / 'static' / 'navbar.js').read_text()
market = (ROOT / 'static' / 'live-market-pro.js').read_text()
market_template = (ROOT / 'templates' / 'live_market_pro.html').read_text()
onboard_py = (ROOT / 'wallet_onboarding.py').read_text()
onboard_js = (ROOT / 'static' / 'wallet-onboarding.js').read_text()
gen_py = (ROOT / 'trading_wallet_generator.py').read_text()
gen_js = (ROOT / 'static' / 'trading-wallet-generator.js').read_text()
verify = (ROOT / 'tools' / 'verify_live.py').read_text()
env_example = (ROOT / 'deploy' / 'env.example').read_text()
portfolio = (ROOT / 'portfolio_multichain_holdings.py').read_text()
history = (ROOT / 'portfolio_trade_history.py').read_text()
registry = (ROOT / 'trade_engine' / 'registry.py').read_text()
providers = (ROOT / 'trade_engine' / 'providers.py').read_text()
portfolio_swap = (ROOT / 'portfolio_sol_swap.py').read_text()

checks = []
def check(name, cond):
    checks.append(bool(cond))
    print(('PASS ' if cond else 'FAIL ') + name)

check('active EVM registry is empty', 'ACTIVE_EVM_CHAINS = {}' in dash)
check('Live Market backend only admits Solana',
      "_MARKET_LIVE_CHAINS = {'solana'}" in dash and "_CALL_LOOKUP_EVM_CHAINS = ()" in dash)
check('navbar search only admits Solana', "_NB_LIVE_CHAINS=['solana'];" in navbar)
check('Live Market has no EVM trade routes',
      'EVM_TRADE_CHAINS' not in market
      and '/api/bsc/trade/' not in market and '/api/evm/trade/' not in market
      and '/api/bridge/' not in market and '/api/trade/quote' not in market)
check('Live Market discovers every public DexScreener Solana home surface',
      'https://api.dexscreener.com/token-boosts/top/v1' in dash
      and 'https://api.dexscreener.com/token-boosts/latest/v1' in dash
      and 'https://api.dexscreener.com/token-profiles/latest/v1' in dash
      and 'https://api.dexscreener.com/community-takeovers/latest/v1' in dash
      and 'https://api.dexscreener.com/ads/latest/v1' in dash)
check('Home and full Live Market share one Solana discovery universe',
      'boost_addrs = _dexscreener_solana_discovery_addresses()' in dash
      and "https://api.dexscreener.com/tokens/v1/solana/" in dash)
check('Home Live Market no longer caps its discovered token list at 30',
      'if len(result) >= 30' not in dash)
check('Live Market enforces a hard $15K market-cap visibility floor',
      '_LIVE_MARKET_MIN_MCAP_USD = 15_000' in dash
      and "token.get('mcap', 0) >= _LIVE_MARKET_MIN_MCAP_USD" in dash
      and "tok.get('market_cap', 0) >= _LIVE_MARKET_MIN_MCAP_USD" in dash
      and "t.get('market_cap', 0) < _LIVE_MARKET_MIN_MCAP_USD" in dash)
check('Live Market scanner no longer truncates discovery to 80/45/30 tokens',
      'return out[:80]' not in dash
      and 'safety_subset = filtered[:45]' not in dash
      and 'tokens = tokens[:30]' not in dash)
check('Live Market frontend shows the complete Solana discovery feed by default',
      "sort: 'trending', minLiquidity: 0" in market
      and 'hideHoneypots: false' in market
      and 'var _LIQ_DEFAULT = 0;' in market
      and 'id="pt-liq-slider" min="0" max="500000" step="5000" value="0"' in market_template)
check('Live Market safety filters do not truncate the candidate universe',
      'filtered[:40]' not in dash
      and 'safety_subset = filtered[:45]' not in dash
      and 'tokens = tokens[:30]' not in dash)
check('Live Market has no extra-chain discovery top-up',
      '_EXTRA_CHAIN_SEARCH_TERMS' not in dash)
check('legacy EVM/bridge URLs are not registered with Flask',
      all(("@app.route('" + route + "'") not in dash for route in (
          '/api/trade/quote', '/api/trade/execute', '/api/bsc/balance',
          '/api/evm/convert-to-usdc', '/api/bridge/quote', '/api/bridge/execute',
          '/api/evm/trade/buy', '/api/bsc/trade/buy', '/api/evm/trade/sell',
          '/api/bsc/trade/sell', '/api/withdraw/evm')))
check('portfolio SOL swap imports only the Jupiter Solana provider',
      'import solana_jupiter_gasless as provider' in portfolio_swap
      and 'solana_source_bridge_gasless' not in portfolio_swap)
check('wallet frontend has no EVM/BSC/bridge request path',
      all(route not in wallet for route in ('/api/evm/', '/api/bsc/', '/api/bridge/', '/api/withdraw/evm')))

# Active runtime boundary: historical helpers/database fields may remain for
# recovery, but no registered Flask route or production-installed adapter may
# execute EVM/0x logic.
route_terms = ('ensure_bsc_wallet', 'get_evm_', '_get_web3', 'is_valid_evm_address',
               'EVM_CHAINS', 'ACTIVE_EVM_CHAINS', '_disabled_evm_quote',
               '_execute_evm_', 'api.0x.org', 'ZEROX')
dash_tree = ast.parse(dash)
dash_lines = dash.splitlines()
active_route_hits = []
for node in dash_tree.body:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    routes = []
    for deco in node.decorator_list:
        if (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)
                and deco.func.attr in ('route', 'get', 'post', 'put', 'delete')
                and deco.args and isinstance(deco.args[0], ast.Constant)):
            routes.append(deco.args[0].value)
    if not routes:
        continue
    body = '\n'.join(dash_lines[node.lineno - 1:node.end_lineno])
    found = [term for term in route_terms if term in body]
    if found:
        active_route_hits.append((node.name, routes, found))
check('no active Flask route contains EVM/0x execution logic', not active_route_hits)

installed_boundary_files = (
    'tip_experience.py', 'portfolio_token_withdraw.py',
    'profile_portfolio_balance.py', 'portfolio_multichain_holdings.py',
    'portfolio_sol_swap.py', 'app_entry.py')
installed_terms = ('EVM_CHAINS', 'ACTIVE_EVM_CHAINS', 'is_valid_evm', 'get_evm_',
                   '_get_web3', '_evm_transfer', 'gasless_evm', 'api.0x.org',
                   'ZEROX', 'allowanceholder')
installed_hits = []
for rel in installed_boundary_files:
    text = (ROOT / rel).read_text()
    found = [term for term in installed_terms if term in text]
    if found:
        installed_hits.append((rel, found))
check('production-installed adapters contain no EVM/0x execution logic', not installed_hits)

for module in ('bsc_gasless_trading', 'sponsored_gas', 'evm_to_solana_bridge',
               'cross_chain_budget_guard', 'multichain_auto_bot',
               'live_market_pooled_buy_balance', 'wallet_deposit_guidance'):
    check(module + ' is not installed at production startup', module not in entry)

check('trade-engine registry contains only Solana',
      "CHAINS: dict = {\n    'solana':" in registry
      and "'bsc': Chain(" not in registry and "'base': Chain(" not in registry)
check('trade-engine exposes Jupiter only',
      'class JupiterProvider' in providers and 'class ZeroExProvider' not in providers)
check('retired 0x/BSC modules are physically removed',
      not (ROOT / 'bsc_gasless_trading.py').exists()
      and not (ROOT / 'sponsored_gas.py').exists())
check('dashboard no longer contains a 0x API URL literal',
      "'https://api.0x.org" not in dash and '"https://api.0x.org' not in dash)
check('dashboard no longer reads a ZEROX API key',
      'ZEROX_API_KEY    =' not in dash and "os.environ.get('ZEROX_API_KEY'" not in dash)
check('deploy example no longer asks for a ZEROX API key', 'ZEROX_API_KEY=' not in env_example)
check('live verifier never reads the ZEROX API key', "getenv('ZEROX_API_KEY')" not in verify
      and 'api.0x.org' not in verify)

for prefix in ("path.startswith('/api/bsc/')", "path.startswith('/api/evm/')",
               "path.startswith('/api/bridge/')", "path == '/api/withdraw/evm'",
               "path == '/admin/bridge-test'"):
    check('legacy route is blocked before execution: ' + prefix, prefix in dash)
check('legacy route blocker returns Solana-only 410',
      "OrcAgent supports Solana only" in dash and '), 410' in dash)

check('wallet identifies Solana mainnet only', 'SOLANA · MAINNET' in wallet and 'MULTI-CHAIN · MAINNET' not in wallet)
check('wallet history filter only offers Solana',
      '<option value="solana">Solana</option>' in wallet
      and '<option value="base">Base</option>' not in wallet
      and '<option value="bsc">BNB Chain</option>' not in wallet
      and '<option value="arbitrum">Arbitrum</option>' not in wallet)
check('wallet has no manual bridge action', '>Bridge USDC</button>' not in wallet)
check('wallet send/convert active arrays have no EVM chain',
      "var _SEND_CHAINS=[" in wallet and "var _CONVERT_CHAINS=[" in wallet
      and "{v:'bsc'" not in wallet[wallet.index('var _SEND_CHAINS=['):wallet.index('function _sendChain')]
      and "{v:'base'" not in wallet[wallet.index('var _CONVERT_CHAINS=['):wallet.index('var _convertQuote')])

for name, text in (('wallet onboarding server', onboard_py), ('wallet onboarding client', onboard_js),
                   ('wallet generator server', gen_py), ('wallet generator client', gen_js)):
    check(name + ' has no EVM private-key flow',
          'evm_private_key' not in text and 'freshEvmKey' not in text)
check('new trading-wallet generation stores only Solana key',
      'bsc_wallet_address=?, encrypted_private_key_bsc=?' not in gen_py)
check('active portfolio snapshot contains no EVM wallet', "wallets={'solana':owner}" in portfolio)
check('portfolio history is Solana-filtered',
      "COALESCE(q.destination_chain,'solana'))='solana'" in history
      and "COALESCE(chain,'solana'))='solana'" in history)

# Static syntax parse of the Python product boundary.
for rel in ('dashboard.py', 'app_entry.py', 'wallet_onboarding.py',
            'trading_wallet_generator.py', 'tools/verify_live.py'):
    ast.parse((ROOT / rel).read_text())
check('all Solana-only Python boundary files parse', True)

raise SystemExit(0 if all(checks) else 1)
