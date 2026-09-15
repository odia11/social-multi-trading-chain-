"""Live Market must not block an automatic cross-chain buy in the browser.

The Live Market controller is IIFE-scoped, so its local balance loader cannot
be replaced through ``window``.  The production fix therefore normalises the
summary response before that controller caches/reads it.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOTFIX = (ROOT / 'live_market_pooled_buy_balance.py').read_text(encoding='utf-8')
ENTRY = (ROOT / 'app_entry.py').read_text(encoding='utf-8')


def check(message, condition):
    assert condition, message
    print('PASS ' + message)


check('production installs the pooled Live Market balance fix',
      'from live_market_pooled_buy_balance import install' in ENTRY
      and '_install_live_market_pooled_buy_balance(_dashboard)' in ENTRY)
check('BUY availability reads the wallet-wide total returned by the summary endpoint',
      'body.total_usdc' in HOTFIX and 'pooledTotal(body)' in HOTFIX)
check('the fallback still totals Solana plus every supported EVM stable balance',
      'd.solana_usdc' in HOTFIX
      and all(c in HOTFIX for c in ('bsc','base','arbitrum','polygon','robinhood')))
check('the fix patches fetch before the IIFE controller can cache destination-only balances',
      'window.fetch = function(input, init)' in HOTFIX
      and "body.replace('</head>'" in HOTFIX)
check('every Live Market EVM balance slot receives the pooled buying power',
      'CHAINS.forEach(function(c){ body.evm_chains[c] = total; })' in HOTFIX)
check('the server remains authority for bridge/execution; browser patch has no key/signing code',
      'private_key' not in HOTFIX and 'requests.' not in HOTFIX)
check('the injected HTML is no-cache so a mobile app cannot keep the old veto',
      'Cache-Control' in HOTFIX and 'no-store' in HOTFIX)

print('\n7/7 checks passed')
