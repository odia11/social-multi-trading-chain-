"""Regression checks for Android/WebView document scrolling.

Home and Portfolio used to depend on :has(body...) to override the dashboard's
root overflow:hidden rule. Older Android WebViews reject the complete selector
list when it contains unsupported :has(), so scroll rules use only root classes.

Android Chromium can also behave badly when both html and body are independent
vertical scrollers. The performance bootstrap therefore makes body the single
native mobile scroll container on Home and Portfolio before the body is parsed.
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
    home_css = NAVBAR_JS.index("ensureStyle('/static/home-mobile.css?v=6'")
    portfolio_class = NAVBAR_JS.index("classList.add('oa-portfolio-root')")
    portfolio_css = NAVBAR_JS.index("ensureStyle('/static/portfolio-redesign.css?v=6'")
    assert home_class < home_css
    assert portfolio_class < portfolio_css


def test_android_uses_one_native_mobile_scroll_owner():
    assert "if path in ('/', '/wallet')" in APP_PERF
    assert 'oa-native-mobile-scroll' in APP_PERF
    assert 'html.oa-native-mobile-scroll{height:100%!important' in APP_PERF
    assert 'overflow:hidden!important' in APP_PERF
    assert 'html.oa-native-mobile-scroll body{height:100dvh!important' in APP_PERF
    assert 'overflow-y:auto!important' in APP_PERF
    assert 'html.oa-native-mobile-scroll body #app{height:auto!important' in APP_PERF
    assert 'overflow:visible!important' in APP_PERF
