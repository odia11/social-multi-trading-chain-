from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = (ROOT / 'static' / 'page-lifecycle.js').read_text()
PERF = (ROOT / 'app_performance.py').read_text()

checks = {
    'lifecycle injected into every HTML response':
        '<script src="/static/page-lifecycle.js?v=2"></script>' in PERF
        and PERF.find('<script src="/static/page-lifecycle.js?v=2"></script>')
        < PERF.find('<script src="/static/bfcache-guard.js?v=2"></script>'),
    'pagehide suspends resources and aborts stale reads':
        "addEventListener('pagehide'" in LIFECYCLE and "suspend('pagehide',true)" in LIFECYCLE,
    'bfcache pages resume managed resources':
        "addEventListener('pageshow'" in LIFECYCLE and "resume(e.persisted?'bfcache':'pageshow')" in LIFECYCLE,
    'background pages pause recurring work':
        "visibilitychange" in LIFECYCLE and "suspend('hidden',false)" in LIFECYCLE,
    'only safe read requests are auto-aborted':
        "method!=='GET'&&method!=='HEAD'" in LIFECYCLE and "return _fetch(input,init)" in LIFECYCLE,
    'managed intervals can be stopped permanently':
        '__oaManagedInterval' in LIFECYCLE and 'intervals.delete(handle)' in LIFECYCLE,
    'managed observers disconnect and re-observe':
        'nativeDisconnect()' in LIFECYCLE and 'rec.watches.forEach' in LIFECYCLE,
    'future long-lived connections have teardown support':
        'trackConnection' in LIFECYCLE and "closeMethod||'close'" in LIFECYCLE,
}
for label, ok in checks.items():
    print(('PASS' if ok else 'FAIL') + ' - ' + label)
    assert ok, label

# theme-light.js is document infrastructure like page-lifecycle.js itself: it
# runs first in <head> (before the lifecycle exists) and its observers keep
# light mode applied for the whole life of the document, bfcache included.
skip_names = {'page-lifecycle.js', 'sw.js', 'token-launch-web3.js', 'theme-light.js'}
bad = []
for root_name in ('static', 'templates'):
    for path in (ROOT / root_name).rglob('*'):
        if path.suffix.lower() not in {'.js', '.html'}:
            continue
        if 'vendor' in path.parts or path.name.endswith('.min.js') or path.name in skip_names:
            continue
        text = path.read_text(errors='ignore')
        unmanaged = []
        if re.search(r'(?<![\w.])setInterval\(', text):
            unmanaged.append('setInterval')
        if re.search(r'(?<![\w.])clearInterval\(', text):
            unmanaged.append('clearInterval')
        if re.search(r'new\s+(?:MutationObserver|ResizeObserver|IntersectionObserver)\(', text):
            unmanaged.append('observer')
        if re.search(r'new\s+(?:WebSocket|EventSource)\(', text):
            unmanaged.append('connection')
        if unmanaged:
            bad.append((path.relative_to(ROOT), unmanaged))

assert not bad, 'Unmanaged page-lifecycle resources: ' + repr(bad)
print('PASS - all first-party page intervals/observers/connections use OrcPageLifecycle')

# Lazy-route contract: Live Market is the heaviest data route and must own all
# recurring/async work through one named route scope. A same-document router
# unmount must therefore be able to abort/close everything without pagehide.
live = (ROOT / 'static' / 'live-market-pro.js').read_text()
redesign = (ROOT / 'static' / 'live-market-redesign.js').read_text()
hotfix = (ROOT / 'static' / 'live-market-hotfix.js').read_text()
pull = (ROOT / 'static' / 'pull-to-refresh.js').read_text()
template = (ROOT / 'templates' / 'live_market_pro.html').read_text()
route_checks = {
    'named route scopes are available for lazy components':
        'routeScope:routeScope' in LIFECYCLE and 'namedScopes=new Map()' in LIFECYCLE,
    'route cleanup aborts reads and clears intervals/timeouts/raf/listeners/observers/connections':
        'scopeReads.forEach' in LIFECYCLE and 'scopeIntervals.forEach' in LIFECYCLE
        and 'timeouts.forEach' in LIFECYCLE and 'rafs.forEach' in LIFECYCLE
        and 'removeEventListener' in LIFECYCLE and 'scopeObservers.forEach' in LIFECYCLE
        and 'connections.forEach' in LIFECYCLE,
    'history navigation cleans lazy route scopes':
        "cleanupRouteScopes('history-push')" in LIFECYCLE
        and "cleanupRouteScopes('history-replace')" in LIFECYCLE
        and "cleanupRouteScopes('popstate')" in LIFECYCLE,
    'detached route roots clean their scope':
        "scope.cleanup('dom-unmount')" in LIFECYCLE,
    'Live Market uses one named scope':
        "routeScope('live-market','.pt-shell')" in live
        and "routeScope('live-market','.pt-shell')" in redesign
        and "routeScope('live-market','.pt-shell')" in hotfix
        and "routeScope('live-market','.pt-shell')" in template,
    'Live Market has no unscoped fetches':
        not re.search(r'(?<![\w.])fetch\(', live) and live.count('_routeScope.fetch(') >= 20,
    'Live Market polling is route-scoped':
        'OrcPageLifecycle.setInterval(' not in live and live.count('_routeScope.setInterval(') >= 5,
    'Live Market timeouts and animation frames are route-scoped':
        not re.search(r'(?<![\w.])setTimeout\(', live)
        and not re.search(r'(?<![\w.])requestAnimationFrame\(', live),
    'Live Market has no direct WebSocket or EventSource':
        not re.search(r'new\s+(?:WebSocket|EventSource)\(', live + redesign + hotfix),
    'pull-to-refresh participates in route cleanup':
        'opts.scope' in pull and 'scope.onCleanup' in pull and 'scope.addEventListener' in pull,
}
for label, ok in route_checks.items():
    print(('PASS' if ok else 'FAIL') + ' - ' + label)
    assert ok, label

print('ALL PAGE LIFECYCLE CLEANUP REGRESSIONS PASSED')
