from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
D=(ROOT/'dashboard.py').read_text()
JS=(ROOT/'static'/'mobile-bottom-nav.js').read_text()
CSS=(ROOT/'static'/'mobile-bottom-nav.css').read_text()
HOME=(ROOT/'static'/'home-mobile.css').read_text()
POLISH=(ROOT/'static'/'home-mobile-polish.css').read_text()

checks={
 'mobile footer is present in server-rendered shared navbar':
      '<nav id="oa-bottom-nav" class="oa-bottom-nav"' in D
      and 'aria-label="Create post"' in D
      and '/static/mobile-bottom-nav.css?v=8' in D
      and '/static/mobile-bottom-nav.js?v=8' in D,
 'client hydrates server footer instead of depending on creating it':
      "document.getElementById('oa-bottom-nav')||_createBottomNav()" in JS
      and "nav.dataset.oaHydrated" in JS,
 'client self-heals missing footer children':
      'if(nav.children.length<5)' in JS and '_createBottomNav()' in JS,
 'home cannot inherit unrelated full-screen classes that hide footer':
      "classList.remove('oa-trade-sheet-open','oa-msgs-typing','oa-thread-open')" in JS,
 'home has one bottom reserve rather than stacked body/app padding':
      'html body.oa-shared-ux.oa-home-mobile{padding-bottom:0!important}' in HOME
      and 'padding-bottom:0!important}' in HOME
      and 'calc(112px + env(safe-area-inset-bottom,0px))' in HOME,
 'composer geometry is explicitly in normal flow':
      '#feed-composer{width:100%!important;box-sizing:border-box!important;position:relative!important;inset:auto!important;transform:none!important' in HOME,
 'polish keeps the same single bottom reserve':
      'calc(112px + env(safe-area-inset-bottom,0px))' in POLISH,
 'corrected footer bundle is cache busted':
      'mobile-bottom-nav.js?v=8' in (ROOT/'static'/'navbar.js').read_text()
      and 'mobile-bottom-nav.css?v=8' in (ROOT/'static'/'navbar.js').read_text(),
}
for label,ok in checks.items():
    print(('PASS' if ok else 'FAIL')+' - '+label)
    assert ok,label
print('ALL HOME MOBILE FOOTER CONTRACTS PASSED')
