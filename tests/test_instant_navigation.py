from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / 'static' / 'page-loader.js').read_text(encoding='utf-8')
UX = (ROOT / 'static' / 'app-ux.js').read_text(encoding='utf-8')

def test_only_one_layer_prefetches_navigation_intent():
    assert "prefetch(closestLink(e))" in UX
    assert "fetchDocument" not in SRC
    assert "primeCore" not in SRC
    assert "X-OrcAgent-Prefetch" not in SRC

def test_loader_keeps_native_navigation_and_safe_progress():
    assert "e.preventDefault()" not in SRC
    assert "document.write" not in SRC
    assert "u.origin!==location.origin" in SRC
    assert "u.pathname.indexOf('/api/')===0" in SRC
    assert "data-no-instant-nav" in SRC
    assert "beforeunload" in SRC
    assert "oa:bfcache-restore" in SRC


def test_core_route_chunks_are_warmed_without_private_document_prefetch():
    assert 'primeRouteAssets' in UX
    assert 'CORE_ROUTES' in UX
    assert "warmRoute(path,false)" in UX
    assert "l.rel=urgent?'preload':'prefetch'" in UX
    assert "l.as='document'" not in UX
    assert 'fetchDocument' not in UX


def test_slow_navigation_uses_shell_but_keeps_native_browser_navigation():
    assert 'showRouteShell' in UX
    assert 'beginRoute(u.pathname)' in UX
    section=UX[UX.index("document.addEventListener('click'"):UX.index("window.addEventListener('pageshow'")]
    assert 'preventDefault' not in section


if __name__ == '__main__':
    for name in sorted(n for n in globals() if n.startswith('test_')):
        globals()[name]()
        print('PASS', name)
    print('ALL INSTANT NAVIGATION REGRESSIONS PASSED')
