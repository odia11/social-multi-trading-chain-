"""Regression checks for the app-wide performance layer.

These are source-level guards because the important failures here are wiring
failures: loading the whole app in the background, watching every DOM mutation,
or letting the shared performance bootstrap disappear from production.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
UX = (ROOT / 'static' / 'app-ux.js').read_text(encoding='utf-8')
CSS = (ROOT / 'static' / 'app-ux.css').read_text(encoding='utf-8')
PERF = (ROOT / 'app_performance.py').read_text(encoding='utf-8')
ENTRY = (ROOT / 'app_entry.py').read_text(encoding='utf-8')
NGINX = (ROOT / 'deploy' / 'nginx-orcagent.conf').read_text(encoding='utf-8')
LOADER = (ROOT / 'static' / 'page-loader.js').read_text(encoding='utf-8')


def check(message, condition):
    assert condition, message
    print('PASS ' + message)


check('the shared UX no longer bulk-prefetches seven authenticated pages',
      'idlePrefetch' not in UX
      and "['/','/live-market','/wallet','/groups','/bot','/messages','/notifications']" not in UX)
check('navigation intent still warms the page a user is actually about to open',
      "['pointerover','touchstart','focusin']" in UX and 'prefetch(closestLink(e))' in UX)
check('below-fold images decode asynchronously and lazy-load',
      "img.decoding='async'" in UX and "img.loading='lazy'" in UX)
check('the app no longer observes class/style mutations on every DOM node',
      ".observe(document.body,{childList:true,subtree:true})" in UX
      and "attributeFilter:['class','style']" in UX
      and ".observe(document.body,{childList:true,subtree:true,attributes:true" not in UX)
check('hidden pages pause decorative CSS animation work',
      'oa-page-hidden' in UX and 'animation-play-state:paused' in CSS)
check('ordinary mobile bottom space is tightened from the old 132px reserve',
      'padding-bottom:calc(108px + env(safe-area-inset-bottom,0px))' in CSS
      and 'calc(132px + env' not in CSS)
check('portfolio gets a compact but safe fixed-nav reserve',
      'body.oa-shared-ux.oa-portfolio .wlt-center' in CSS)
check('every HTML response gets the current shared performance assets early',
      'app-ux.css?v=5' in PERF and 'app-ux.js?v=4' in PERF)
check('route-critical redesign assets are applied before first paint',
      'portfolio-redesign.css?v=6' in PERF
      and 'live-market-redesign.css?v=7' in PERF
      and 'home-mobile.css?v=8' in PERF
      and 'home-mobile-polish.css?v=6' in PERF)
check('production WSGI installs the performance adapter',
      'from app_performance import install as _install_app_performance' in ENTRY
      and '_install_app_performance(_dashboard)' in ENTRY)
check('fallback loader no longer duplicates document prefetching',
      'app-ux.css?v=5' in LOADER and 'app-ux.js?v=4' in LOADER
      and 'fetchDocument' not in LOADER and 'primeCore' not in LOADER)
check('nginx compresses text assets while retaining live proxy streaming',
      'gzip on;' in NGINX and 'application/javascript' in NGINX
      and 'proxy_buffering off;' in NGINX)
check('static assets keep bounded caching with background revalidation',
      'max-age=604800' in NGINX and 'stale-while-revalidate=86400' in NGINX)


check('same-origin documents opt in to browser-managed route transitions',
      '@view-transition' in CSS and 'navigation: auto' in CSS
      and '::view-transition-old(root)' in CSS
      and '::view-transition-new(root)' in CSS)
check('private no-store HTML is never prefetched',
      "l.as='document'" not in UX and "l.href=u.pathname+u.search" not in UX)
check('route asset prefetch is restricted to public versioned CSS/JS',
      "var ROUTE_ASSETS" in UX and "var key='/static/'+asset" in UX
      and 'navigator.connection.saveData' in UX)
check('portfolio boot does not hide its entire document',
      'visibility:hidden!important' not in (ROOT / 'static' / 'navbar.js').read_text(encoding='utf-8'))

check('dashboard chart engine is lazy instead of render-blocking',
      'lightweight-charts.standalone.production.js?v=4.1.3" defer' not in (ROOT/'dashboard.html').read_text(encoding='utf-8')
      and '_ensureLightweightCharts' in (ROOT/'static'/'dashboard.js').read_text(encoding='utf-8'))
check('noncritical dashboard hydration is staggered through idle work',
      '_oaIdle' in (ROOT/'static'/'dashboard.js').read_text(encoding='utf-8')
      and "_safeInit('loadHomeFeed', loadHomeFeed())" in (ROOT/'static'/'dashboard.js').read_text(encoding='utf-8'))
check('normal deploys repair nginx static compression on Certbot sites',
      'apply-nginx-performance.sh' in (ROOT/'deploy'/'install.sh').read_text(encoding='utf-8'))

print('\n20/20 checks passed')
