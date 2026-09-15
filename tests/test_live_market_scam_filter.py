"""Focused policy tests for the default Live Market scam filter."""
import ast
import os

path = os.path.join(os.path.dirname(__file__), '..', 'dashboard.py')
source = open(path, encoding='utf-8').read()
tree = ast.parse(source)
node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
            and n.name == '_scanner_token_passes_scam_filter')
ns = {}
exec(ast.get_source_segment(source, node), ns)
passes = ns['_scanner_token_passes_scam_filter']


def token(chain='solana', liquidity=150000, volume=300000, buys=60, sells=40):
    return {'chain': chain, 'liquidity_usd': liquidity, 'volume_24h': volume,
            'buys_24h': buys, 'sells_24h': sells}


sol_safe = {'ok': True, 'mint_authority_active': False,
            'freeze_authority_active': False}
assert passes(token(), sol_safe)
assert not passes(token(), {**sol_safe, 'mint_authority_active': True})
assert not passes(token(), {**sol_safe, 'freeze_authority_active': True})
assert not passes(token(liquidity=24999), sol_safe)
assert not passes(token(buys=100, sells=0), sol_safe)
assert not passes(token(buys=99, sells=1), sol_safe)

evm_safe = {'ok': True, 'is_honeypot': False, 'buy_tax': 2, 'sell_tax': 3}
assert passes(token('bsc'), evm_safe)
assert not passes(token('bsc'), {**evm_safe, 'is_honeypot': True})
assert not passes(token('bsc'), {**evm_safe, 'sell_tax': 20})
assert not passes(token('base'), {**evm_safe, 'risk_level': 'very high'})

unknown = {'ok': False, 'is_honeypot': True, 'no_provider': True}
assert passes(token('robinhood'), unknown)
assert not passes(token('robinhood', liquidity=90000), unknown)
assert not passes(token('robinhood', sells=5, buys=95), unknown)

print('live market scam-filter tests passed')
