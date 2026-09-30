"""Regression checks for the standalone Messages Home-style token card."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "static" / "messages-ui.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "messages-ui.css").read_text(encoding="utf-8")
INJECTOR = (ROOT / "messages_premium_ui.py").read_text(encoding="utf-8")
LIVE_MARKET = (ROOT / "static" / "live-market-pro.js").read_text(encoding="utf-8")


def test_dm_card_uses_live_token_info_banner_and_price():
    assert "/api/token/info/" in JS
    assert "info.banner_url" in JS
    assert "info.price_usd" in JS
    assert "data-dm-live-price" in JS


def test_dm_card_opens_correct_token_inside_live_market():
    assert "'/live-market?mint='+encodeURIComponent(mint)+'&profile=1'" in JS
    assert "window.location.href=route" in JS
    assert "'/token/' + encodeURIComponent(mint)" not in JS
    # The live Live Market opens that token's profile, and still honours the
    # older ?addr= links already sitting in people's DMs.
    assert "var _qMint = _qs.get('mint') || _qs.get('addr');" in LIVE_MARKET
    assert "(_qs.get('addr') && !_qs.get('mint'))) _profileMint=_qMint;" in LIVE_MARKET


def test_old_dm_trade_payloads_keep_existing_renderer():
    assert "originalRender=window._renderDmTokenCard" in JS
    assert "if(!mint && originalRender)return originalRender(tr)" in JS


def test_copy_trade_logic_is_not_replaced():
    assert "_copyTrades" not in JS


def test_assets_are_loaded_on_messages_page():
    assert "messages-ui.css" in INJECTOR
    assert "messages-ui.js" in INJECTOR
    assert ".dm-home-token-card" in CSS
