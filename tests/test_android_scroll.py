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
    home_css = NAVBAR_JS.index("ensureStyle('/static/home-mobile.css?v=7'")
    portfolio_class = NAVBAR_JS.index("classList.add('oa-portfolio-root')")
    portfolio_css = NAVBAR_JS.index("ensureStyle('/static/portfolio-redesign.css?v=7'")
    assert home_class < home_css
    assert portfolio_class < portfolio_css


def test_android_uses_document_element_as_single_native_scroll_owner():
    assert "_root_scroll_excluded = ('/messages', '/live-market')" in APP_PERF
    assert "if path not in _root_scroll_excluded" in APP_PERF
    assert 'oa-native-mobile-scroll' in APP_PERF
    assert 'html.oa-native-mobile-scroll{height:auto!important' in APP_PERF
    assert 'overflow-y:auto!important' in APP_PERF
    assert 'html.oa-native-mobile-scroll body{height:auto!important' in APP_PERF
    assert 'overflow:visible!important' in APP_PERF
    assert 'html.oa-native-mobile-scroll body #app{height:auto!important' in APP_PERF
    assert 'html.oa-native-mobile-scroll.oa-modal-open' in APP_PERF
    assert 'html.oa-native-mobile-scroll.oa-wallet-actions-open' in APP_PERF
    assert 'html.oa-native-mobile-scroll.oa-app-menu-open' in APP_PERF
    assert 'oa-android-scroll' in APP_PERF
    assert 'body.oa-home-mobile #main-content.wrap' in APP_PERF
    assert 'overflow-y:auto!important' in APP_PERF
    assert 'touch-action:pan-y!important' in APP_PERF
