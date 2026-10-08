"""Home balance must match the authoritative Portfolio snapshot."""
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
JS=(ROOT/'static'/'home-mobile.js').read_text()
CSS=(ROOT/'static'/'home-mobile.css').read_text()
NAV=(ROOT/'static'/'navbar.js').read_text()
UX=(ROOT/'static'/'app-ux.js').read_text()
PERF=(ROOT/'app_performance.py').read_text()

checks={
  'home header does not hide the shared balance chip':
      # The rule may also name html.oa-route-home (the same header from the
      # first paint), so match the selector inside a selector list.
      not re.search(r'body\.oa-home-mobile \.pt-nb-sol-chip[^{]*\{display:none!important\}', CSS)
      and re.search(r'body\.oa-home-mobile \.pt-nb-sol-chip[^{]*\{display:flex!important', CSS) is not None,
  'narrow phones preserve balance by collapsing wordmark instead':
      '@media(max-width:430px)' in CSS and '.pt-nb-wordmark{display:none!important}' in CSS,
  'home portfolio reads the authoritative aggregate snapshot':
      "fetch('/api/portfolio/snapshot?t='" in JS,
  'home no longer recomputes portfolio from three drifting endpoints':
      "var urls=['/api/wallet/usdc-summary','/api/wallet/tokens','/api/wallet/balance']" not in JS,
  'home paints last confirmed value synchronously':
      'orcaPortfolioLastConfirmedUSDCValue' in JS and '_homeCachedPortfolio()' in JS,
  'home snapshot also synchronizes the shared header':
      "new CustomEvent('orca:portfolio-value'" in JS,
  'changed home bundles resolve to the current deploy hash everywhere':
      'home-mobile.css?v=15' in NAV and 'home-mobile.js?v=16' in NAV
      and "'home-mobile.css'" in UX and "'home-mobile.js'" in UX
      and 'staticBuildUrl(asset)' in UX
      and "lambda m: m.group(1) + '?v=' + version" in PERF,
}
for label,ok in checks.items():
    print(('PASS' if ok else 'FAIL')+' - '+label)
    assert ok,label
print('ALL HOME BALANCE CONSISTENCY CONTRACTS PASSED')
