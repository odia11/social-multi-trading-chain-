from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'static' / 'shared-trade-card-v2.js').read_text(encoding='utf-8')
CSS = (ROOT / 'static' / 'shared-trade-card-v2.css').read_text(encoding='utf-8')
PERF = (ROOT / 'app_performance.py').read_text(encoding='utf-8')
GROUP = (ROOT / 'templates' / 'group_detail.html').read_text(encoding='utf-8')


def test_groups_legacy_renderer_is_now_wrapped_by_shared_component():
    assert 'function _renderTradeCardHtml' in GROUP
    assert "patch('_renderTradeCardHtml')" in JS
    assert 'OrcAgentTradeCard' in JS


def test_messages_uses_same_runtime_renderer():
    assert "patch('_renderDmTokenCard')" in JS
    assert '/live-market?addr=' in JS


def test_legacy_records_without_mint_fall_back_to_original_renderer():
    assert "if(!t.mint){return typeof fallback==='function'?fallback(raw):''}" in JS


def test_shared_assets_are_injected_on_every_html_page():
    assert 'shared-trade-card-v2.css' in PERF
    assert 'shared-trade-card-v2.js' in PERF


def test_shared_card_has_banner_live_price_and_mobile_layout():
    assert 'data-oa-stc-banner' in JS
    assert 'data-oa-stc-live' in JS
    assert '.oa-stc-banner' in CSS
    assert '@media(max-width:767px)' in CSS
