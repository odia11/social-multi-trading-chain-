"""Live Market buy sheet: Solana only, spent in SOL, a manual trade.

Trades are funded with native SOL since #155 (it said USDC before), and Live
Market buys are manual since 25a607d: no stop-loss/take-profit is attached;
the bot's protection is for the bot's own positions."""
import os, re, subprocess
REPO=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS=open(REPO+'/static/live-market-pro.js').read()
HTML=open(REPO+'/templates/live_market_pro.html').read()
checks=[]
def check(name,cond): checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ')+name)

check('live-market-pro.js parses',
      subprocess.run(['node','--check',REPO+'/static/live-market-pro.js'],capture_output=True).returncode==0)
check('buy sheet labels what you spend', "'You spend'" in JS)
check('buy confirms through Solana instant-trade only',
      "var url = '/api/instant-trade';" in JS)
check('buy sends token identity and the SOL amount',
      'token_address:t.mint' in JS and "currency:'SOL', amount_sol:amt" in JS)
check('EVM/BSC buy routes are absent',
      '/api/bsc/trade/buy' not in JS and '/api/evm/trade/buy' not in JS)
check('bridge polling is absent',
      '/api/bridge/status/' not in JS and '_pollAutoBuyBridge' not in JS)
check('EVM quote execution is absent from confirm path',
      "'/api/trade/execute'" not in JS)
check('success reports the realized amount when returned',
      'd.sol_amount' in JS and "'Bought '" in JS)
check('buy receipt remains visible after success',
      '_showTxReceipt(idx, t, d)' in JS)
check('a Live Market buy is a manual trade: no automatic SL/TP attached',
      'body.protect = false;' in JS and 'body.sl_pct' not in JS)
check('trade sheet styles still exist', '.pt-sheet' in HTML and '.pt-slide' in HTML)

raise SystemExit(0 if all(checks) else 1)
