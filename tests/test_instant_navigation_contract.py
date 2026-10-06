"""Protected deployment contract for OrcAgent instant navigation."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
UX=(ROOT/'static'/'app-ux.js').read_text()
CSS=(ROOT/'static'/'app-ux.css').read_text()
SW=(ROOT/'static'/'sw.js').read_text()
PERF=(ROOT/'app_performance.py').read_text()
LOADER=(ROOT/'static'/'page-loader.js').read_text()
UPDATE=(ROOT/'deploy'/'update.sh').read_text()
INSTALL=(ROOT/'deploy'/'install.sh').read_text()

checks={
  'native navigation remains authoritative':
      'document.write' not in UX and 'fetchDocument' not in UX,
  'navigation HTML is only warmed in ephemeral service-worker RAM':
      'oa-nav-prefetch' in UX and 'OA_NAV_READY = new Map()' in SW
      and "cache:'no-store'" in SW and "fetch('/api/" not in UX,
  'core route static chunks are warmed with exact destination build URLs':
      'primeRouteAssets' in UX and 'CORE_ROUTES' in UX and 'warmRoute(path,false)' in UX
      and 'staticBuildUrl(asset)' in UX,
  'hover warms assets while touch/pointer-down may warm one document':
      "['pointerover','focusin']" in UX and "['pointerdown','touchstart']" in UX
      and 'warmRoute(u.pathname,true)' in UX and 'warmDocument(u)' in UX,
  'slow navigation gets a stable app-shell placeholder':
      'showRouteShell' in UX and '.oa-route-shell{' in CSS,
  'warm destinations skip the shell while cold routes paint it before Safari can freeze the old page':
      "n.className='oa-route-shell show'" in UX
      and 'if(!warm)showRouteShell(path);' in UX
      and 'window.__oaSkipNextRouteShell=warm' in UX
      and "d.type==='oa-nav-ready'" in UX,
  'route families warm nested profile and message assets':
      'ROUTE_ASSETS[routeKey(path)]' in UX and "path.indexOf(base+'/')===0" in UX,
  'programmatic navigation gets a beforeunload shell fallback without warm-route reflash':
      'OrcAgentShowRouteShell' in UX and 'OrcAgentShowRouteShell' in LOADER
      and '!window.__oaSkipNextRouteShell' in LOADER,
  'shared shell assets preload from head':
      'data-oa-shell-preload' in PERF and 'mobile-bottom-nav.css?v=9' in PERF,
  'shared UX is cache-busted consistently by the deploy hash':
      "lambda m: m.group(1) + '?v=' + version" in PERF
      and 'oa-app-version' in LOADER and 'encodeURIComponent(oaBuild)' in LOADER
      and "register('/sw.js?v='+encodeURIComponent(APP_VERSION||'1'))" in UX,
  'service worker runtime cache is public static GET only':
      "url.pathname.indexOf('/static/')!==0" in SW
      and "url.origin!==self.location.origin" in SW
      and "req.method!=='GET'" in SW,
  'service worker reuses ephemeral navigation warmup without caching HTML':
      "if(req.mode==='navigate')" in SW
      and 'oaNavigationResponse(event,req,navHref)' in SW
      and 'OA_NAV_READY = new Map()' in SW
      and "cache:'no-store'" in SW and 'resp.redirected' in SW
      and "url.pathname.indexOf('/static/')!==0" in SW,
  'this performance contract is enforced by update and install':
      'check-performance-contract.sh' in UPDATE
      and 'check-performance-contract.sh' in INSTALL,
}
for label,ok in checks.items():
    print(('PASS' if ok else 'FAIL')+' - '+label)
    assert ok,label
print('ALL INSTANT NAVIGATION DEPLOYMENT CONTRACTS PASSED')
