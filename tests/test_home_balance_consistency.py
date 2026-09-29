"""Home balance must match the authoritative Portfolio snapshot."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
JS=(ROOT/'static'/'home-mobile.js').read_text()
CSS=(ROOT/'static'/'home-mobile.css').read_text()
NAV=(ROOT/'static'/'navbar.js').read_text()
UX=(ROOT/'static'/'app-ux.js').read_text()
PERF=(ROOT/'app_performance.py').read_text()

checks={
  'home header does not hide the shared balance chip':
      'body.oa-home-mobile .pt-nb-sol-chip{display:none!important}' not in CSS
      and 'body.oa-home-mobile .pt-nb-sol-chip{display:flex!important' in CSS,
  'narrow phones preserve balance by collapsing wordmark instead':
      '@media(max-width:430px)' in CSS and '.pt-nb-wordmark{display:none!important}' in CSS,
  'home portfolio reads the authoritative aggregate snapshot':
      "fetch('/api/portfolio/snapshot?t='" in JS,
  'home no longer recomputes portfolio from three drifting endpoints':
      "var urls=['/api/wallet/usdc-summary','/api/wallet/tokens','/api/wallet/balance']" not in JS,
  'home paints last confirmed value synchronously':
      'orcaPortfolioLastConfirmedTotal' in JS and '_homeCachedPortfolio()' in JS,
  'home snapshot also synchronizes the shared header':
      "new CustomEvent('orca:portfolio-value'" in JS,
  'changed home bundles are cache-busted everywhere':
      'home-mobile.css?v=11' in NAV and 'home-mobile.js?v=10' in NAV
      and 'home-mobile.css?v=11' in UX and 'home-mobile.js?v=10' in UX
      and 'home-mobile.css?v=11' in PERF,
}
for label,ok in checks.items():
    print(('PASS' if ok else 'FAIL')+' - '+label)
    assert ok,label
print('ALL HOME BALANCE CONSISTENCY CONTRACTS PASSED')
