/* Android scroll, app-wide. Chrome may only start a touch scroll on the
   compositor when no NON-passive touchstart/touchmove listener covers the
   touch point -- one on window/document/body covers EVERY point on the page.
   Live Market's slide-to-confirm knob registered exactly that, just to stop
   the page scrolling while the knob is dragged; CSS touch-action:none on the
   knob does that job without blocking the rest of the page.

   Also: body must never become a second scroll container. overflow-x:hidden
   on body turns its overflow-y into auto; overflow-x:clip trims the same
   overflow without creating a scroll container. */
const assert=require('node:assert/strict');
const fs=require('node:fs');

// swipe-back.js is the one deliberate exception: it attaches its
// non-passive document touchmove ONLY for a touch that started in the
// left-edge zone, and removes it the moment that touch ends or turns out
// not to be a horizontal back-swipe.
const ALLOWED={'static/swipe-back.js':1};
const GLOBAL=/(?:\bwindow|\bdocument(?:\.body|\.documentElement)?)\.addEventListener\(\s*['"](touchstart|touchmove|wheel)['"][^;]*?passive\s*:\s*false/g;
const files=[...fs.readdirSync('static').filter(f=>f.endsWith('.js')).map(f=>'static/'+f),
             ...fs.readdirSync('templates').filter(f=>f.endsWith('.html')).map(f=>'templates/'+f),'dashboard.html'];
for(const f of files){
  const src=fs.readFileSync(f,'utf8');
  const hits=src.match(GLOBAL)||[];
  assert(hits.length<=(ALLOWED[f]||0), f+': non-passive page-wide touch/wheel listener blocks scrolling on Android: '+hits.join(' | '));
}

// Live Market's slide-to-confirm: passive touch, CSS does the blocking.
const lm=fs.readFileSync('static/live-market-pro.js','utf8');
const slide=lm.slice(lm.indexOf('(function bindSlide(){'),lm.indexOf('(function bindSheetDrag(){'));
assert(/document\.addEventListener\('touchstart', down, \{passive:true\}\)/.test(slide));
assert(/document\.addEventListener\('touchmove',  move, \{passive:true\}\)/.test(slide));
assert(/if\(!e\.touches\) e\.preventDefault\(\)/.test(slide),'only mouse drags may preventDefault');
assert(/\.pt-slide-knob\{touch-action:none;/.test(fs.readFileSync('templates/live_market_pro.html','utf8')),'the knob itself must opt out of panning');

// body is never a scroll container on mobile pages.
for(const [f,re] of [['static/app-ux.css',/body\{max-width:100%;overflow-x:hidden;overflow-x:clip;/],
                     ['static/live-market-mobile-drawer-fix.css',/overflow-x:hidden!important;overflow-x:clip!important/],
                     ['static/live-market-redesign.css',/body\.oa-live-v2\{[^}]*overflow-x:hidden!important;overflow-x:clip!important/]])
  assert(re.test(fs.readFileSync(f,'utf8')),f+': body needs overflow-x:clip after the hidden fallback');
for(const [f,n] of [['app_performance.py','app-ux.css?v=7'],['app_performance.py','live-market-redesign.css?v=8'],
                    ['static/page-loader.js','app-ux.css?v=7'],['static/navbar.js','live-market-redesign.css?v=8'],
                    ['static/app-ux.js','live-market-redesign.css?v=8'],['mobile_ui_hotfix.py','live-market-mobile-drawer-fix.css?v=2']])
  assert(fs.readFileSync(f,'utf8').includes(n),f+' must cache-bust '+n);

// /history: the filter bar only exists when there are trades.
assert(/function _fval\(id, dflt\)/.test(fs.readFileSync('templates/history.html','utf8')));
console.log('PASS Android scroll on every page: no page-wide blocking touch listeners, body never a scroll container');
