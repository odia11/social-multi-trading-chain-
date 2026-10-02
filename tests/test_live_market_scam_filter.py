"""Focused policy tests for the Solana-only Live Market scam filter."""
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

# Healthy Solana mints stay discoverable regardless of market-size/activity.
# Those are optional Live Market filters now, not hidden scam heuristics.
assert passes(token(), sol_safe)
assert passes(token(liquidity=100), sol_safe)
assert passes(token(volume=0, buys=0, sells=0), sol_safe)

# Concrete Solana authority risks still fail closed.
assert not passes(token(), {**sol_safe, 'ok': False})
assert not passes(token(), {**sol_safe, 'mint_authority_active': True})
assert not passes(token(), {**sol_safe, 'freeze_authority_active': True})

# OrcAgent is Solana-only; stale/non-Solana scanner entries never pass.
for chain in ('bsc', 'base', 'arbitrum', 'polygon', 'robinhood'):
    assert not passes(token(chain), sol_safe)

print('live market Solana scam-filter tests passed')
