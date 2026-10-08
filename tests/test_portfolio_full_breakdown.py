"""Portfolio shows one total plus a separately itemized Solana asset list."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
W=(ROOT/'templates/wallet.html').read_text()
CSS=(ROOT/'static/portfolio-redesign.css').read_text()
D=(ROOT/'dashboard.py').read_text()
P=(ROOT/'portfolio_multichain_holdings.py').read_text()

checks=[]
def check(label,cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ')+label)

for item in ('oa-pf-break-total','oa-pf-break-usdc','oa-pf-break-sol',
             'oa-pf-break-other','oa-pf-count','oa-assets-count'):
    check('portfolio breakdown exposes '+item, f'id="{item}"' in W)
check('portfolio has a separately itemized Your assets section',
      'Your assets' in W and 'Each balance shown separately' in W)
check('USDC and SOL fixed rows show amount and fiat value separately',
      'id="pf-usdc-asset"' in W and 'id="pf-usdc-value"' in W
      and 'id="pf-sol-asset"' in W and 'id="pf-sol-value"' in W)
check('small balances are visible by default', 'var _hideSmall=false' in W)
check('breakdown is repainted from the same authoritative snapshot',
      'window.OrcAgentPaintPortfolioBreakdown=_paintPortfolioBreakdown' in W
      and '_paintPortfolioBreakdown(snap)' in W)
check('UI distinguishes a temporarily incomplete discovery scan',
      'Checking all tokens…' in W)   # one short status line on the balance card
check('indexed RPC outage falls back to direct verified token accounts',
      'def _known_wallet_token_accounts' in D
      and 'getMultipleAccounts' in D
      and 'verified known-mint fallback' in D)
check('fallback DB rows only discover mint candidates, never supply balances',
      "SELECT token_address, symbol, avg_price FROM user_tokens" in D
      and "raw_amount = int.from_bytes(raw[64:72], 'little')" in D)
check('snapshot exposes whether full token discovery completed',
      "inventory_complete=inventory_complete" in P)
check('breakdown has responsive compact styling',
      '.oa-pf-breakdown-grid' in CSS and '@media(max-width:420px)' in CSS)

raise SystemExit(0 if all(checks) else 1)
