/* Android Home scroll: Chrome may only start a touch scroll on the
   compositor when no NON-passive touchstart/touchmove listener covers the
   touch point. Two such listeners made Home feel like it wouldn't scroll:
     1. home-start-trading-route.js put a {passive:false} touchstart (and
        pointerdown) on window -- every touch on the page waited for JS, and
        passive:false also opted out of Chrome's intervention that makes
        window-level touch listeners passive.
     2. Every feed like-button carried inline ontouchstart/ontouchmove
        attributes, which are always non-passive -- a blocking spot in every
        feed card.
   Plus the CSS side: only html may be the scroller; body must stay
   overflow:visible or it becomes a second, nested scroll container. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

const route=fs.readFileSync('static/home-start-trading-route.js','utf8');
const code=route.replace(/\/\*[\s\S]*?\*\//g,'');
assert(!/addEventListener\(\s*'(touchstart|touchmove|pointerdown)'/.test(code),'the Start Trading guard must not listen to touch/pointerdown');
assert(!/passive\s*:\s*false/.test(code),'no non-passive listeners in the Start Trading guard');
assert(/window\.addEventListener\('click',intercept,true\)/.test(code),'the guard still intercepts the click in capture phase');
assert(fs.readFileSync('mobile_ui_hotfix.py','utf8').includes('home-start-trading-route.js?v=2'),'the fixed guard must be cache-busted');

// The app-wide Start Trading guard must not navigate on touchend: that also
// fires when a scroll merely started on the CTA.
const guard=fs.readFileSync('static/auto-bot-route-guard.js','utf8').replace(/\/\*[\s\S]*?\*\//g,'').replace(/\/\/.*$/gm,'');
assert(!/addEventListener\(\s*'(touchstart|touchend|touchmove|pointerdown|pointerup)'/.test(guard),'auto-bot-route-guard.js must only use click');
assert(fs.readFileSync('auto_trading_bot_route.py','utf8').includes('auto-bot-route-guard.js?v=2'),'the fixed app-wide guard must be cache-busted');

// No inline touch handlers anywhere a page renders from: they are always
// non-passive and there is no way to make them passive.
const files=[...fs.readdirSync('static').filter(f=>f.endsWith('.js')).map(f=>'static/'+f),
             ...fs.readdirSync('templates').filter(f=>f.endsWith('.html')).map(f=>'templates/'+f),'dashboard.html'];
for(const f of files){
  const s=fs.readFileSync(f,'utf8');
  assert(!/\sontouch(start|move)\s*=/.test(s),f+' must not use inline ontouchstart/ontouchmove attributes');
}
const dash=fs.readFileSync('static/dashboard.js','utf8');
assert(dash.includes('data-like-press="'),'like buttons carry data-like-press for the delegated long-press');
for(const ev of ['touchstart','touchmove','touchend','touchcancel'])
  assert(new RegExp("document\\.addEventListener\\('"+ev+"',function\\([^)]*\\)\\{[^]*?_fcLike[^]*?\\},\\{passive:true\\}\\)").test(dash),
    'like long-press '+ev+' must be a passive delegated listener');

// One scroller: html. body stays overflow:visible on mobile Home.
const css=fs.readFileSync('static/home-mobile.css','utf8');
const bodyRule=css.match(/body\.oa-home-mobile\{[^}]*\}/)[0];
assert(/overflow:visible!important/.test(bodyRule)&&!/overflow-(x|y):/.test(bodyRule),'home-mobile.css: body must be overflow:visible, never overflow-x/y');
assert(/html\.oa-home-mobile-root\{[^}]*overflow-y:auto!important[^}]*-webkit-overflow-scrolling:touch/.test(css),'html is the scroller, with touch scrolling');
const polish=fs.readFileSync('static/home-mobile-polish.css','utf8');
assert(!/body\.oa-home-mobile\{[^}]*overflow-y:auto/.test(polish)&&!/,body\.oa-home-mobile\{overflow-y:auto/.test(polish),'polish must not make body a scroller');
assert(/body\.oa-home-mobile\{overflow:visible!important/.test(polish));

// Every place that loads these assets agrees on the new versions.
for(const [f,needles] of Object.entries({
  'static/navbar.js':['home-mobile.css?v=9','home-mobile.js?v=9'],
  'static/app-ux.js':['home-mobile.css?v=9','home-mobile-polish.css?v=7','home-mobile.js?v=9'],
  'static/home-mobile.js':['home-mobile-polish.css?v=7'],
  'app_performance.py':['home-mobile.css?v=9','home-mobile-polish.css?v=7']}))
  for(const n of needles) assert(fs.readFileSync(f,'utf8').includes(n),f+' must reference '+n);
console.log('PASS Android Home scroll: no blocking touch listeners, no inline touch handlers, html is the only scroller');
