"""Every buy surface must use USDC on every supported chain."""
import ast
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(REPO, 'dashboard.py'), encoding='utf-8').read()
CARD = open(os.path.join(REPO, 'static', 'token-card.js'), encoding='utf-8').read()
TREE = ast.parse(SRC)


def fn(name):
    node = next(n for n in ast.walk(TREE)
                if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SRC, node) or ''


def check(message, condition):
    assert condition, message
    print('PASS ' + message)


legacy = fn('api_trade_buy')
flow = fn('_solana_buy_flow')

check('the older Solana endpoint joins the shared USDC-funded buy flow',
      '_solana_buy_flow(' in legacy)
check('the older endpoint prefers amount_usdc while accepting the legacy field',
      "data.get('amount_usdc', data.get('amount_sol'))" in legacy)
check('the older endpoint cannot call a SOL-funded swap directly',
      '_execute_user_swap_ex' not in legacy and 'current_sol < amount_sol' not in legacy)
check('a requested amount below the minimum is refused, never increased',
      'float(requested_usdc) < min_trade_usdc' in flow
      and 'Minimum trade amount is' in flow)
check('a requested amount above the maximum is capped safely',
      'min(max_trade_usdc, float(requested_usdc))' in flow)
check('the shared Solana swap explicitly uses the configured USDC base',
      'base=SOLANA_BASE_CURRENCY' in flow)
check('Robinhood is an EVM chain in the shared token card',
      "['base', 'arbitrum', 'polygon', 'robinhood']" in CARD)
check('the token card routes every EVM buy to the EVM endpoint',
      "url = side === 'buy' ? '/api/evm/trade/buy'" in CARD)
check('the token card labels every chain in USDC',
      "function _tcUnit(chain){ return 'USDC'; }" in CARD)

evm = fn('_evm_buy_flow')
check('EVM buys also refuse a sub-minimum amount instead of increasing it',
      'amount_usdc < min_size' in evm and 'Minimum trade amount is' in evm)

print('\n10/10 checks passed')
