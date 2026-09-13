from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / 'static' / 'page-loader.js').read_text(encoding='utf-8')


def test_warm_navigation_is_safe_and_session_aware():
    assert "credentials:'include'" in SRC
    assert "X-OrcAgent-Prefetch" in SRC
    assert "WARM_TTL=15000" in SRC
    assert "WARM_MAX=6" in SRC
    assert "data-no-instant-nav" in SRC
    assert "u.origin!==location.origin" in SRC
    assert "u.pathname.indexOf('/api/')===0" in SRC


def test_core_routes_are_prefetched_without_blocking_first_paint():
    for route in ("'/'", "'/live-market'", "'/messages'", "'/wallet'"):
        assert route in SRC
    assert 'requestIdleCallback' in SRC


def test_click_only_soft_navigates_when_document_is_already_warm():
    assert 'if(hit&&hit.html)' in SRC
    assert 'e.preventDefault()' in SRC
    assert "document.open('text/html','replace')" in SRC
    assert 'document.write(html)' in SRC
    assert 'location.href=u.href' in SRC
