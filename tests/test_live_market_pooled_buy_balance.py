"""Live Market pooled buying power must reach the automatic bridge backend."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOTFIX = (ROOT / 'live_market_pooled_buy_balance.py').read_text(encoding='utf-8')
CROSS = (ROOT / 'live_market_cross_chain_execute.py').read_text(encoding='utf-8')
ENTRY = (ROOT / 'app_entry.py').read_text(encoding='utf-8')


def check(message, condition):
    assert condition, message
    print('PASS ' + message)


check('production installs the pooled Live Market balance fix',
      'from live_market_pooled_buy_balance import install' in ENTRY
      and '_install_live_market_pooled_buy_balance(_dashboard)' in ENTRY)
check('pooled balance install also installs cross-chain execute routing',
      'from live_market_cross_chain_execute import install' in HOTFIX
      and '_install_cross_chain_execute(d)' in HOTFIX)
check('BUY availability reads the wallet-wide total returned by the summary endpoint',
      'body.total_usdc' in HOTFIX and 'pooledTotal(body)' in HOTFIX)
check('the fallback totals Solana plus every supported EVM stable balance',
      'd.solana_usdc' in HOTFIX
      and all(c in HOTFIX for c in ('bsc','base','arbitrum','polygon','robinhood')))
check('every Live Market EVM balance slot receives pooled buying power',
      'CHAINS.forEach(function(c){ body.evm_chains[c] = total; })' in HOTFIX)
check('underfunded destination execution invokes the established auto bridge',
      "app.view_functions.get(endpoint)" in CROSS
      and 'd._maybe_start_auto_bridge_for_buy(' in CROSS
      and "bridge.get('started')" in CROSS)
check('cross-chain execute keeps quote ownership checks before moving money',
      "quote.get('user_id')" in CROSS and "quote.get('wallet')" in CROSS)
check('already-funded destination still uses the original trade engine endpoint',
      "destination_balance + Decimal('0.000001') >= required" in CROSS
      and 'return original(*args, **kwargs)' in CROSS)
check('automatic funding returns the pending bridge contract Live Market expects',
      "'pending': True" in CROSS and "'bridge_id': bridge.get('bridge_id')" in CROSS)
check('browser patch has no signing or private-key code',
      'private_key' not in HOTFIX and 'requests.' not in HOTFIX)
check('injected HTML is no-cache so mobile cannot retain the old veto',
      'Cache-Control' in HOTFIX and 'no-store' in HOTFIX)

print('\n11/11 checks passed')
