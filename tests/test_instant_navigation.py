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


def test_core_route_chunks_are_warmed_and_html_intent_goes_to_service_worker():
    assert 'primeRouteAssets' in UX
    assert 'CORE_ROUTES' in UX
    assert "warmRoute(path,false)" in UX
    assert "l.rel=urgent?'preload':'prefetch'" in UX
    assert "l.as='document'" not in UX
    assert 'fetchDocument' not in UX
    assert "type:'oa-nav-prefetch'" in UX
    assert 'navigator.serviceWorker.controller.postMessage(msg)' in UX


def test_navigation_shell_is_visible_before_native_navigation_freezes_old_page():
    assert 'showRouteShell' in UX
    assert 'beginRoute(u.pathname)' in UX
    assert "n.className='oa-route-shell show'" in UX
    assert 'showRouteShell(path);' in UX
    assert 'setTimeout(function(){showRouteShell(path)},120)' not in UX
    section=UX[UX.index("document.addEventListener('click'"):UX.index("window.addEventListener('pageshow'")]
    assert 'preventDefault' not in section


def test_nested_profile_routes_use_profile_asset_family():
    assert 'function routeKey(path)' in UX
    assert "path.indexOf(base+'/')===0" in UX
    assert 'ROUTE_ASSETS[routeKey(path)]' in UX


def test_beforeunload_covers_programmatic_navigation():
    assert 'OrcAgentShowRouteShell' in SRC


if __name__ == '__main__':
    for name in sorted(n for n in globals() if n.startswith('test_')):
        globals()[name]()
        print('PASS', name)
    print('ALL INSTANT NAVIGATION REGRESSIONS PASSED')
