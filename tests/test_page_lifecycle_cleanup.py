from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = (ROOT / 'static' / 'page-lifecycle.js').read_text()
PERF = (ROOT / 'app_performance.py').read_text()

checks = {
    'lifecycle injected into every HTML response':
        '<script src="/static/page-lifecycle.js?v=1"></script>' in PERF
        and PERF.find('<script src="/static/page-lifecycle.js?v=1"></script>')
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

skip_names = {'page-lifecycle.js', 'sw.js', 'token-launch-web3.js'}
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
print('ALL PAGE LIFECYCLE CLEANUP REGRESSIONS PASSED')
