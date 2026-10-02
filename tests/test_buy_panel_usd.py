"""Live Market buy sheet is Solana/USDC-only."""
import os, re, subprocess
REPO=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS=open(REPO+'/static/live-market-pro.js').read()
HTML=open(REPO+'/templates/live_market_pro.html').read()
checks=[]
def check(name,cond): checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ')+name)

check('live-market-pro.js parses',
      subprocess.run(['node','--check',REPO+'/static/live-market-pro.js'],capture_output=True).returncode==0)
check('buy sheet labels spend in USDC', "'You spend'" in JS and "'USDC'" in JS)
check('buy confirms through Solana instant-trade only',
      "var url = '/api/instant-trade';" in JS)
check('buy sends token identity and USDC amount',
      'token_address:t.mint' in JS and 'amount_usdc:amt' in JS)
check('cached-backend compatibility amount is still sent',
      'amount_sol:amt' in JS)
check('EVM/BSC buy routes are absent',
      '/api/bsc/trade/buy' not in JS and '/api/evm/trade/buy' not in JS)
check('bridge polling is absent',
      '/api/bridge/status/' not in JS and '_pollAutoBuyBridge' not in JS)
check('EVM quote execution is absent from confirm path',
      "'/api/trade/execute'" not in JS)
check('success reports realized USDC amount when returned',
      'd.amount_usdc' in JS and "'Bought '" in JS)
check('buy receipt remains visible after success',
      '_showTxReceipt(idx, t, d)' in JS)
check('protection remains attached to buy',
      'body.protect = prot.protect' in JS and 'body.sl_pct' in JS and 'body.tp_pct' in JS)
check('trade sheet styles still exist', '.pt-sheet' in HTML and '.pt-slide' in HTML)

raise SystemExit(0 if all(checks) else 1)
