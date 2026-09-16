"""Regression checks for the standalone Messages Home-style token card."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "static" / "messages-ui.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "messages-ui.css").read_text(encoding="utf-8")
INJECTOR = (ROOT / "messages_premium_ui.py").read_text(encoding="utf-8")
# NOT templates/live_market.html -- that template is unrouted (see
# dashboard.py's live_market() docstring: "previous mobile-oriented template
# is kept on disk, unrouted, in case it's needed again"). /live-market serves
# live_market_pro.html, whose own JS resolves a deep-linked token through its
# ?mint= param (live-market-pro.js), not the retired ?addr= / showTokenCard()
# path this test used to check on a page nothing ever serves.
LIVE_MARKET_JS = (ROOT / "static" / "live-market-pro.js").read_text(encoding="utf-8")


def test_dm_card_uses_live_token_info_banner_and_price():
    assert "/api/token/info/" in JS
    assert "info.banner_url" in JS
    assert "info.price_usd" in JS
    assert "data-dm-live-price" in JS


def test_dm_card_opens_correct_token_inside_live_market():
    assert "'/live-market?mint='+encodeURIComponent(mint)" in JS
    assert "window.location.href=route" in JS
    assert "'/token/' + encodeURIComponent(mint)" not in JS
    assert "new URLSearchParams(location.search).get('mint')" in LIVE_MARKET_JS


def test_old_dm_trade_payloads_keep_existing_renderer():
    assert "originalRender=window._renderDmTokenCard" in JS
    assert "if(!mint && originalRender)return originalRender(tr)" in JS


def test_copy_trade_logic_is_not_replaced():
    assert "_copyTrades" not in JS


def test_assets_are_loaded_on_messages_page():
    assert "messages-ui.css" in INJECTOR
    assert "messages-ui.js" in INJECTOR
    assert ".dm-home-token-card" in CSS
