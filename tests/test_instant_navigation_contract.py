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
  'private HTML and APIs are not prefetched':
      "l.as='document'" not in UX and "fetch('/api/" not in UX,
  'core route static chunks are warmed':
      'primeRouteAssets' in UX and 'CORE_ROUTES' in UX and 'warmRoute(path,false)' in UX,
  'touch/pointer intent upgrades the target route chunks':
      "['pointerover','touchstart','focusin']" in UX and 'warmRoute(u.pathname,true)' in UX,
  'slow navigation gets a stable app-shell placeholder':
      'showRouteShell' in UX and '.oa-route-shell{' in CSS,
  'fast navigation does not flash the placeholder':
      'setTimeout(function(){showRouteShell(path)},120)' in UX,
  'shared shell assets preload from head':
      'data-oa-shell-preload' in PERF and 'mobile-bottom-nav.css?v=9' in PERF,
  'shared UX is cache-busted consistently':
      'app-ux.css?v=8' in PERF and 'app-ux.js?v=8' in PERF
      and 'app-ux.css?v=8' in LOADER and 'app-ux.js?v=8' in LOADER,
  'service worker runtime cache is public static GET only':
      "url.pathname.indexOf('/static/')!==0" in SW
      and "url.origin!==self.location.origin" in SW
      and "req.method!=='GET'" in SW,
  'service worker never caches navigation documents':
      "event.request.mode==='navigate'" not in SW,
  'this performance contract is enforced by update and install':
      'check-performance-contract.sh' in UPDATE
      and 'check-performance-contract.sh' in INSTALL,
}
for label,ok in checks.items():
    print(('PASS' if ok else 'FAIL')+' - '+label)
    assert ok,label
print('ALL INSTANT NAVIGATION DEPLOYMENT CONTRACTS PASSED')
