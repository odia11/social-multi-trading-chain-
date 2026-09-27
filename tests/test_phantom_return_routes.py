"""Regression checks for Phantom return routing.

Run directly from the repository root:
    python3 tests/test_phantom_return_routes.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'static' / 'dashboard.js').read_text()
ONBOARD = (ROOT / 'static' / 'wallet-onboarding.js').read_text()
CALLBACK = (ROOT / 'templates' / 'phantom_callback.html').read_text()

checks = []
def check(name, condition):
    checks.append((name, bool(condition)))
    print(('PASS ' if condition else 'FAIL ') + name)

check('mobile browser uses signed Phantom connect instead of opening its embedded dApp browser',
      '_phantomMobileV1Connect(afterLoginUrl); return;' in JS
      and "window.location.href='https://phantom.app/ul/v1/connect?'" in JS
      and 'phantom.app/ul/browse/' not in JS)
check('wallet setup on standalone pages hands off to signed browser login preserving current route',
      '/?wallet_connect=phantom&return_to=' in ONBOARD
      and 'location.pathname+location.search+location.hash' in ONBOARD
      and 'phantom_connect=1' not in ONBOARD)
check('standalone-page browser handoff consumes once and restores original same-origin path',
      "url.searchParams.get('wallet_connect') !== 'phantom'" in JS
      and "url.searchParams.delete('wallet_connect')" in JS
      and "_safeWalletReturnRoute(url.searchParams.get('return_to') || '/')" in JS
      and "_phantomMobileV1Connect(returnTo)" in JS)
check('legacy Phantom dApp browse links remain compatible without issuing new browse links',
      "u.searchParams.get('phantom_connect') !== '1'" in JS
      and "connectWalletOnboard('phantom', returnTo)" in JS)
check('mobile browsers and installed PWAs both pair across callback/default-browser boundaries',
      "var _pairPromise = fetch('/api/pair/start'" in JS
      and '_storePairToken(d.pair)' in JS
      and '_storePairReturnRoute(_returnRoute)' in JS
      and "if(!_pair){" in JS)
check('return recovery prioritizes newly signed pairing even when prior account is still logged in',
      'if(_pairToken()){' in JS and 'if(newlyPaired) wallet = newlyPaired;' in JS)
check('deliberate Disconnect clears pending pair and saved return destination',
      "_clearPairToken();" in JS[JS.index('function disconnectWallet()'):JS.index('function _obSkipKey()')]
      and "localStorage.removeItem('orca_pair_return')" in JS[JS.index('function disconnectWallet()'):JS.index('function _obSkipKey()')])
check('iPadOS desktop-class user agent is still treated as mobile for Phantom approval',
      'navigator.maxTouchPoints > 1' in JS)
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
