"""Source guards for the September 2026 frontend cleanup."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
PERF = (ROOT / 'app_performance.py').read_text()
MOBILE = (ROOT / 'mobile_ui_hotfix.py').read_text()
NAV = (ROOT / 'static' / 'navbar.js').read_text()
HOME = (ROOT / 'static' / 'home-mobile.js').read_text()
MESSAGES = (ROOT / 'messages_premium_ui.py').read_text()

def test_route_css_is_applied_before_first_paint():
    assert 'rel="stylesheet"' in PERF and 'rel="preload"' not in PERF
    for asset in ('portfolio-redesign.css','live-market-redesign.css','home-mobile.css','groups-redesign.css'):
        assert asset in PERF

def test_navbar_does_not_append_duplicate_assets():
    assert 'function ensureStyle' in NAV and 'function ensureScript' in NAV

def test_obsolete_auth_controllers_are_not_shipped():
    for asset in ('navbar-connect-state.js','guest-menu-auth-fix.js','mobile-nav-post-force.js'):
        assert asset not in MOBILE
    assert 'ensureMobileConnectButton' not in HOME

def test_route_specific_mobile_assets_are_scoped():
    assert "if path == '/':" in MOBILE and "elif path == '/live-market':" in MOBILE

def test_messages_use_two_bundles():
    assert 'messages-ui.css?v=1' in MESSAGES and 'messages-ui.js?v=1' in MESSAGES
    assert 'messages-premium-v2.css' not in MESSAGES
