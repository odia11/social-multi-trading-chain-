"""Live Market must not block an automatic cross-chain buy in the browser.

A user can hold USDC on one supported chain and buy on another.  The server's
buy flow owns the auto-bridge.  Therefore the BUY sheet may display the pooled
USDC spending balance, but must never veto a Robinhood/Base/etc buy merely
because the destination-chain balance is zero.
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
check('BUY availability uses the wallet-wide total returned by the existing summary endpoint',
      'summary.total_usdc' in HOTFIX)
check('the fallback still totals Solana plus every supported EVM stable balance',
      'summary.solana_usdc' in HOTFIX
      and all(c in HOTFIX for c in ('bsc','base','arbitrum','polygon','robinhood')))
check('the browser override replaces the old destination-only balance loader',
      'window._loadSheetBalance = function(_chain)' in HOTFIX)
check('the server remains the authority for bridging; the fix adds no transfer or signing logic',
      '_maybe_start_auto_bridge_for_buy' in HOTFIX
      and 'private_key' not in HOTFIX
      and 'requests.' not in HOTFIX)
check('the injected HTML is no-cache so an installed mobile app cannot keep the old veto',
      "Cache-Control" in HOTFIX and 'no-store' in HOTFIX)

print('\n6/6 checks passed')
