"""Legacy EVM withdrawal regression: product is Solana-only now."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
D=(ROOT/'dashboard.py').read_text()
T=(ROOT/'portfolio_token_withdraw.py').read_text()
W=(ROOT/'static/portfolio-token-send.js').read_text()

checks=[]
def check(label,cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ')+label)

check('legacy EVM withdrawal route is blocked before execution',
      "path == '/api/withdraw/evm'" in D and '), 410' in D)
check('blocker explains the current Solana-only product',
      'OrcAgent supports Solana only' in D)
check('active portfolio token withdrawal accepts only Solana',
      "@app.post('/api/wallet/send-token')" in T
      and "if chain != 'solana':" in T)
check('portfolio send UI has only Solana chain metadata',
      "var CHAIN={solana:'Solana'}" in W and 'base:' not in W and 'bsc:' not in W)
check('native SOL still routes through authenticated wallet send',
      "url='/api/wallet/send'" in W and 'amount_sol:amount' in W)
check('SPL/USDC sends route through token withdrawal',
      "url='/api/wallet/send-token'" in W and 'token_address:a.token' in W)
check('token route re-validates recipient, amount and on-chain balance server-side',
      'to_address' in T and 'amount is None' in T
      and 'send_raw > balance_raw' in T)
check('withdrawal mutation has CSRF, throttling and duplicate protection',
      '_csrf_ok(d)' in T and "_rate_ok('withdraw_wallet:' + wallet" in T
      and 'already submitted recently' in T)

raise SystemExit(0 if all(checks) else 1)
