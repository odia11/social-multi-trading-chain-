"""Guest startup must never render the retired full-screen onboarding."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "dashboard.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "dashboard.js").read_text(encoding="utf-8")


def test_legacy_onboarding_is_hidden_before_first_paint():
    assert '<div id="onboard" class="hide" aria-hidden="true">' in HTML
    css = HTML[HTML.index("#onboard{"):HTML.index("}", HTML.index("#onboard{"))]
    assert "display:none" in css
    assert '<div id="app" style="display:block">' in HTML


def test_signed_out_startup_goes_directly_to_public_feed():
    startup = JS[JS.index("(async function initApp()"):JS.index("var _sessionReturnPromise")]
    assert "guestMode=true;" in startup
    assert "await launchApp();" in startup


def test_manual_disconnect_stays_on_public_feed():
    logout = JS[JS.index("function doLogout()"):JS.index("// ── ONBOARDING")]
    assert "guestMode=true;" in logout
    assert "classList.add('hide')" in logout
    assert "launchApp()" in logout
    assert "classList.remove('hide')" not in logout


def test_connect_uses_current_wallet_sheet_not_legacy_screen():
    start = JS.index("function _guestConnect()")
    guest_connect = JS[start:JS.index("function checkGuest()", start)]
    assert "OrcAgentWalletOnboarding.open()" in guest_connect
    assert "classList.remove('hide')" not in guest_connect
