"""Regression checks for Phantom return routing.

Run directly from the repository root:
    python3 tests/test_phantom_return_routes.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'static' / 'dashboard.js').read_text()
CALLBACK = (ROOT / 'templates' / 'phantom_callback.html').read_text()

checks = []
def check(name, condition):
    checks.append((name, bool(condition)))
    print(('PASS ' if condition else 'FAIL ') + name)

check('mobile connect records whether login started in the installed app',
      "source:isStandalonePWA?'pwa':'browser'" in JS)
check('mobile connect sends the original same-app route through Phantom',
      'return_to:_returnRoute' in JS)
check('installed app keeps its return route inside its own storage container',
      "localStorage.setItem('orca_pair_return'" in JS)
check('pair claim consumes the route only after verified login completes',
      '_pairedReturnRoute = _takePairReturnRoute()' in JS)
check('the installed app restores the route after its session is ready',
      JS.count('_finishPairedReturn();') >= 2)
check('dashboard rejects cross-origin and callback return destinations',
      "u.origin !== window.location.origin" in JS
      and "u.pathname === '/phantom-callback'" in JS)
check('the signMessage callback preserves source context and return route',
      "source:fromInstalledApp?'pwa':'browser'" in CALLBACK
      and 'return_to:returnTo' in CALLBACK)
check('ordinary browsers return automatically to their original OrcAgent route',
      'window.location.replace(returnTo)' in CALLBACK)
check('installed-app login shows return-to-app guidance instead of redirecting Safari',
      'Connected to OrcAgent' in CALLBACK
      and 'return to the OrcAgent app' in CALLBACK)
check('callback rejects external and recursive callback redirects',
      "u.origin !== window.location.origin" in CALLBACK
      and "u.pathname === '/phantom-callback'" in CALLBACK)

passed = sum(ok for _, ok in checks)
print(f'\n{passed}/{len(checks)} checks passed')
raise SystemExit(0 if passed == len(checks) else 1)
