"""The X button always completes through direct API or official composer."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'static' / 'dashboard.js').read_text(encoding='utf-8')
ENTRY = (ROOT / 'app_entry.py').read_text(encoding='utf-8')

start = JS.index('function _xShareIntent(')
end = JS.index('\nfunction _feedToggleRepost(', start)
share = JS[start:end]

def test_direct_x_success_accepts_both_backend_success_shapes():
    assert "d.ok===true||d.success===true" in share
    assert "d.fallback!==true" in share
    assert "✓ Shared to X!" in share

def test_failed_api_always_uses_official_x_composer():
    assert "twitter.com/intent/tweet" in share
    assert "_openXShareFallback(postId,d&&d.share_url)" in share
    assert ".catch(function(){ _openXShareFallback(postId,''); })" in share
    assert "Failed to share to X" not in share
    assert "Could not share to X" not in share

def test_fallback_keeps_canonical_post_and_card_preview():
    assert "window.location.origin+'/post/'+encodeURIComponent(postId)" in share
    assert "?xv=9" in share
    assert "@orcagent" in share

def test_server_supplied_redirect_is_restricted_to_x_intent():
    for host in ("twitter.com", "www.twitter.com", "x.com", "www.x.com"):
        assert host in share
    assert "u.pathname==='/intent/tweet'" in share

def test_obsolete_global_fetch_monkeypatch_is_not_installed():
    assert 'x_share_fallback' not in ENTRY
