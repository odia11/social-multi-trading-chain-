"""Regression checks for the standalone Messages Home-style token card."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "static" / "messages-home-token-card-v1.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "messages-home-token-card-v1.css").read_text(encoding="utf-8")
INJECTOR = (ROOT / "messages_premium_ui.py").read_text(encoding="utf-8")


def test_dm_card_uses_live_token_info_banner_and_price():
    assert "/api/token/info/" in JS
    assert "info.banner_url" in JS
    assert "info.price_usd" in JS
    assert "data-dm-live-price" in JS


def test_dm_card_opens_standalone_token_page():
    assert "'/token/' + encodeURIComponent(mint)" in JS
    assert "window.location.href=route" in JS


def test_old_dm_trade_payloads_keep_existing_renderer():
    assert "originalRender=window._renderDmTokenCard" in JS
    assert "if(!mint && originalRender)return originalRender(tr)" in JS


def test_copy_trade_logic_is_not_replaced():
    assert "_copyTrades" not in JS


def test_assets_are_loaded_on_messages_page():
    assert "messages-home-token-card-v1.css" in INJECTOR
    assert "messages-home-token-card-v1.js" in INJECTOR
    assert ".dm-home-token-card" in CSS
