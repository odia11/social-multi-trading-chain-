"""Portfolio Receive is Solana-only."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'templates'/'wallet.html').read_text()

checks=[]
def check(name,cond): checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ')+name)

check('portfolio is labelled Solana mainnet', 'SOLANA · MAINNET' in html)
check('deposit card exposes only SOL tab',
      'data-chain="sol"' in html and 'data-chain="bsc"' not in html)
check('Receive always resolves to Solana trading address',
      "function _rxAddr(){ return _walletAddr }" in html)
check('Receive explorer is Solscan only',
      "var scanUrl='https://solscan.io/account/'" in html
      and 'https://blockscan.com/address/' not in html)
check('Receive has no EVM network switch',
      "_modalDeposit(\'evm\')" not in html and '>EVM chains</button>' not in html)
check('Receive copy/share are Solana only',
      "function _rxCopy(){\n  _copyAddr()" in html
      and "title:'My USDC address (Solana)'" in html)
check('send chain options contain only Solana',
      "{v:'solana', label:'Solana (SOL)'" in html
      and "{v:'bsc'" not in html[html.index('var _SEND_CHAINS=['):html.index('function _sendChain')])
check('convert chain options contain only Solana',
      "{v:'solana',label:'Solana'" in html
      and "{v:'base'" not in html[html.index('var _CONVERT_CHAINS=['):html.index('var _convertQuote')])
check('manual bridge button is gone', '>Bridge USDC</button>' not in html)

raise SystemExit(0 if all(checks) else 1)
