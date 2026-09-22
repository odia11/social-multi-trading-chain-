"""Regression checks for Android/WebView document scrolling.

Home and Portfolio used to depend on :has(body...) to override the dashboard's
root overflow:hidden rule. Older Android WebViews reject the complete selector
list when it contains unsupported :has(), so scroll rules use only root classes.

In standards-mode Android Chromium, document.documentElement is the root
scrollingElement. Keep html as the only vertical document scroller and let body
and the app shells grow naturally; do not create a second body scroller.
"""
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
HOME_CSS = (ROOT / 'static' / 'home-mobile.css').read_text(encoding='utf-8')
HOME_POLISH = (ROOT / 'static' / 'home-mobile-polish.css').read_text(encoding='utf-8')
HOME_JS = (ROOT / 'static' / 'home-mobile.js').read_text(encoding='utf-8')
PORTFOLIO_CSS = (ROOT / 'static' / 'portfolio-redesign.css').read_text(encoding='utf-8')
PORTFOLIO_JS = (ROOT / 'static' / 'portfolio-redesign.js').read_text(encoding='utf-8')
NAVBAR_JS = (ROOT / 'static' / 'navbar.js').read_text(encoding='utf-8')
APP_PERF = (ROOT / 'app_performance.py').read_text(encoding='utf-8')
CHART_SCRUB = (ROOT / 'static' / 'chart-scrub.js').read_text(encoding='utf-8')
LIVE_PRO = (ROOT / 'static' / 'live-market-pro.js').read_text(encoding='utf-8')


def test_home_scroll_does_not_require_has_support():
    assert 'html.oa-home-mobile-root' in HOME_CSS
    assert 'html.oa-home-mobile-root' in HOME_POLISH
    assert 'html:has(' not in HOME_CSS
    assert 'html:has(' not in HOME_POLISH
    assert "document.documentElement.classList.add('oa-home-mobile-root')" in HOME_JS
    assert 'overflow-y:auto!important' in HOME_CSS
    assert 'touch-action:pan-y!important' in HOME_CSS


def test_portfolio_scroll_does_not_require_has_support():
    assert 'html.oa-portfolio-root' in PORTFOLIO_CSS
    assert 'html:has(' not in PORTFOLIO_CSS
    assert "document.documentElement.classList.add('oa-portfolio-root')" in PORTFOLIO_JS
    assert "document.documentElement.classList.add('oa-portfolio-root')" in NAVBAR_JS
    assert 'overflow-y:auto!important' in PORTFOLIO_CSS


def test_route_bootstrap_sets_scroll_classes_before_dynamic_assets():
    home_class = NAVBAR_JS.index("classList.add('oa-home-mobile-root')")
    home_css = NAVBAR_JS.index("ensureStyle('/static/home-mobile.css?v=8'")
    portfolio_class = NAVBAR_JS.index("classList.add('oa-portfolio-root')")
    portfolio_css = NAVBAR_JS.index("ensureStyle('/static/portfolio-redesign.css?v=7'")
    assert home_class < home_css
    assert portfolio_class < portfolio_css


def test_android_and_ios_share_one_document_root_scroller():
    assert "_root_scroll_excluded_prefixes = ('/messages', '/live-market')" in APP_PERF
    assert "_uses_internal_mobile_scroller = any(" in APP_PERF
    assert "path.startswith(prefix + '/')" in APP_PERF
    assert "if not _uses_internal_mobile_scroller" in APP_PERF
    assert 'oa-native-mobile-scroll' in APP_PERF
    assert 'html.oa-native-mobile-scroll{height:auto!important' in APP_PERF
    assert 'overflow-y:auto!important' in APP_PERF
    assert 'html.oa-native-mobile-scroll body{height:auto!important' in APP_PERF
    assert 'overflow:visible!important' in APP_PERF
    assert 'html.oa-native-mobile-scroll body #app{height:auto!important' in APP_PERF
    assert 'html.oa-native-mobile-scroll.oa-modal-open' in APP_PERF
    assert 'html.oa-native-mobile-scroll.oa-wallet-actions-open' in APP_PERF
    assert 'html.oa-native-mobile-scroll.oa-app-menu-open' in APP_PERF
    # Android must no longer get a viewport-height inner #main-content scroller.
    assert 'oa-android-scroll' not in APP_PERF
    assert 'body.oa-home-mobile #main-content.wrap' not in APP_PERF


def test_vertical_swipes_started_on_charts_are_never_hijacked():
    # Shared LightweightCharts scrub waits for a clear horizontal gesture.
    assert "container.style.touchAction = 'pan-y pinch-zoom'" in CHART_SCRUB
    assert "Math.abs(dx) > Math.abs(dy) * 1.15 ? 'scrub' : 'scroll'" in CHART_SCRUB
    assert "if(touchIntent !== 'scrub'){ clearScrub(); return; }" in CHART_SCRUB
    assert "if(e.cancelable) e.preventDefault();" in CHART_SCRUB

    # Live Market's active custom SVG scrub follows the same rule. Vertical
    # intent is handed back to the browser; only a clear horizontal scrub
    # cancels the touch event.
    assert "wrap.style.touchAction = 'pan-y pinch-zoom'" in LIVE_PRO
    assert "touchIntent = Math.abs(dx) > Math.abs(dy) * 1.15 ? 'scrub' : 'scroll'" in LIVE_PRO
    assert "if(touchIntent !== 'scrub'){ clearScrub(); return; }" in LIVE_PRO
    assert "if(e.cancelable) e.preventDefault();" in LIVE_PRO
