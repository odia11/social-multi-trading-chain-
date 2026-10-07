"""Live Market buying power follows the current Solana-only product."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ENTRY=(ROOT/'app_entry.py').read_text()
DASH=(ROOT/'dashboard.py').read_text()
JS=(ROOT/'static/live-market-pro.js').read_text()

checks=[]
def check(label,cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ')+label)

check('retired multichain pooled-balance patch is not installed',
      'live_market_pooled_buy_balance import install' not in ENTRY)
check('backend declares Solana-only live trading',
      'SOLANA_ONLY = True' in DASH and 'ACTIVE_EVM_CHAINS = {}' in DASH)
check('Live Market buy sends a SOL amount to the Solana instant-trade route (#155)',
      "'/api/instant-trade'" in JS and "currency:'SOL', amount_sol:amt" in JS)
check('Live Market no longer routes buys through EVM or bridge endpoints',
      "'/api/evm/trade/buy'" not in JS
      and "'/api/bsc/trade/buy'" not in JS
      and 'pending_bridge' not in JS)
check('buy sheet reads the shared Solana trading balance',
      'ptPooledTotal' in JS or 'PT_USDC_TOTAL' in JS or 'pt-sheet-avail' in JS)

raise SystemExit(0 if all(checks) else 1)
