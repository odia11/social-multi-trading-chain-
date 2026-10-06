from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
JS=(ROOT/'static'/'mobile-bottom-nav.js').read_text()
CSS=(ROOT/'static'/'mobile-bottom-nav.css').read_text()
APP=(ROOT/'static'/'app-ux.css').read_text()
BF=(ROOT/'static'/'bfcache-guard.js').read_text()
SW=(ROOT/'static'/'sw.js').read_text()

checks={
 'bottom nav is fixed and forcibly visible':
      'position:fixed!important' in CSS and 'bottom:0!important' in CSS
      and 'transform:none!important' in CSS and 'visibility:visible!important' in CSS,
 'Safari visualViewport is not used to translate the footer':
      'visibleBottom-nav.getBoundingClientRect().bottom' not in JS
      and 'translate3d(0,' not in JS,
 'old bfcache geometry is explicitly cleared':
      "setProperty('--oa-nav-lift','0px')" in JS
      and "setProperty('transform','none','important')" in JS,
 'page never reserves a second visual-viewport lift':
      'var(--oa-nav-lift' not in CSS and 'var(--oa-nav-lift' not in APP,
 'both legacy navs are forcibly hidden':
      '#mobile-nav,#mob-bottom-nav{display:none!important}' in CSS,
 'bfcache helper does not silence native pageshow listeners':
      'stopImmediatePropagation' not in BF,
 'service worker boot cache uses the corrected nav + lifecycle bundles':
      'orcagent-static-v14' in SW and 'mobile-bottom-nav.js?v=10' in SW
      and 'mobile-bottom-nav.css?v=9' in SW and 'page-lifecycle.js?v=2' in SW,
}
for label,ok in checks.items():
    print(('PASS' if ok else 'FAIL')+' - '+label)
    assert ok,label
print('ALL SAFARI MOBILE CHROME REGRESSIONS PASSED')
