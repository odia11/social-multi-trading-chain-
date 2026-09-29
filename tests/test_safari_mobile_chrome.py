from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
JS=(ROOT/'static'/'mobile-bottom-nav.js').read_text()
CSS=(ROOT/'static'/'mobile-bottom-nav.css').read_text()
APP=(ROOT/'static'/'app-ux.css').read_text()
BF=(ROOT/'static'/'bfcache-guard.js').read_text()
SW=(ROOT/'static'/'sw.js').read_text()

checks={
 'large Safari toolbar corrections are allowed': 'Math.max(-360,Math.min(180,next))' in JS and 'Math.abs(next)>120' not in JS,
 'keyboard is detected by focused text input instead of a magic gap': "_editingText()" in JS and "vv.height < layoutH*0.72" in JS,
 'nav recalculates on bfcache and visibility restore': "orca:bfcache-restored" in JS and "visibilitychange" in JS,
 'page reserves the visual-viewport nav lift': '--oa-nav-lift' in CSS and '--oa-nav-lift' in APP,
 'both legacy navs are forcibly hidden': '#mobile-nav,#mob-bottom-nav{display:none!important}' in CSS,
 'bfcache helper does not silence native pageshow listeners': 'stopImmediatePropagation' not in BF,
 'service worker boot cache uses the new nav bundle': 'orcagent-static-v2' in SW and 'mobile-bottom-nav.js?v=6' in SW,
}
for label,ok in checks.items():
    print(('PASS' if ok else 'FAIL')+' - '+label)
    assert ok,label
print('ALL SAFARI MOBILE CHROME REGRESSIONS PASSED')
