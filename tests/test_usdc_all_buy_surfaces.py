"""Every active OrcAgent buy surface is Solana/USDC only."""
import ast, os
REPO=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC=open(os.path.join(REPO,'dashboard.py'),encoding='utf-8').read()
LM=open(os.path.join(REPO,'static','live-market-pro.js'),encoding='utf-8').read()
TREE=ast.parse(SRC)

def fn(name):
    node=next(n for n in ast.walk(TREE) if isinstance(n,ast.FunctionDef) and n.name==name)
    return ast.get_source_segment(SRC,node) or ''
def check(message,condition):
    assert condition,message; print('PASS '+message)

legacy=fn('api_trade_buy'); flow=fn('_solana_buy_flow')
check('older Solana endpoint joins shared USDC-funded flow','_solana_buy_flow(' in legacy)
check('older endpoint prefers amount_usdc while accepting legacy field',
      "data.get('amount_usdc', data.get('amount_sol'))" in legacy)
check('older endpoint cannot call SOL-funded swap directly',
      '_execute_user_swap_ex' not in legacy and 'current_sol < amount_sol' not in legacy)
check('sub-minimum requested amount is refused',
      'float(requested_usdc) < min_trade_usdc' in flow and 'Minimum trade amount is' in flow)
check('requested amount above maximum is capped',
      'min(max_trade_usdc, float(requested_usdc))' in flow)
check('Solana swap explicitly uses configured USDC base','base=SOLANA_BASE_CURRENCY' in flow)
check('Live Market contains no EVM trade-chain router','EVM_TRADE_CHAINS' not in LM
      and '/api/bsc/trade/' not in LM and '/api/evm/trade/' not in LM)
check('backend live-chain set contains only Solana',"_MARKET_LIVE_CHAINS = {'solana'}" in SRC)
check('legacy EVM requests fail closed before execution',
      "path.startswith('/api/evm/')" in SRC and "path.startswith('/api/bsc/')" in SRC
      and 'OrcAgent supports Solana only' in SRC)
print('\n9/9 checks passed')
