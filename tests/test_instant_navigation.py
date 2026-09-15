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
