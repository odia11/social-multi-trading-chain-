const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const css=fs.readFileSync('static/mobile-bottom-nav.css','utf8');
const home=fs.readFileSync('dashboard.html','utf8');
const boot=fs.readFileSync('static/navbar.js','utf8');
const js=fs.readFileSync('static/mobile-bottom-nav.js','utf8');
assert.match(css,/\.oa-bottom-nav\{[^}]*position:fixed!important;[^}]*bottom:0!important;[^}]*box-sizing:border-box!important/);
assert(!css.includes('box-sizing:content-box'));
assert(home.includes('viewport-fit=cover'));
assert(boot.includes('mobile-bottom-nav.css?v=6'));
assert(boot.includes('mobile-bottom-nav.js?v=6'));
const start=js.indexOf('var _dockFrame=0;'),end=js.indexOf('function build(){',start);
assert(start>=0&&end>start);
let shift=0,changes=0,editing=false;
const rootStyle={vars:{},setProperty(k,v){this.vars[k]=v}};
const nav={dataset:{},style:{setProperty(key,value,priority){assert.equal(key,'transform');assert.equal(priority,'important');shift=Number(value.slice(value.indexOf(',')+1,value.indexOf('px')));changes++}},getClientRects(){return [1]},getBoundingClientRect(){return {bottom:734+shift}}};
const vv={offsetTop:0,height:760};
const ctx={window:{visualViewport:vv,innerHeight:844,matchMedia:()=>({matches:true})},document:{
  getElementById:()=>nav,
  get activeElement(){return editing?{tagName:'TEXTAREA'}:{tagName:'BODY'}},
  documentElement:{clientHeight:844,style:rootStyle}
},Number,Math,requestAnimationFrame:fn=>{fn();return 1}};
vm.createContext(ctx);vm.runInContext(js.slice(start,end),ctx);
ctx._dockBottomNav();
assert.equal(shift,26,'nav must close a measured 26px viewport gap');
ctx._dockBottomNav();
assert.equal(changes,1,'aligned navbar must not jitter or re-transform');

// Expanded Safari chrome can move the visible bottom by far more than 120px.
// The old guard refused this correction and left the nav behind Safari.
vv.height=560;
ctx._dockBottomNav();
assert.equal(shift,-174,'nav must follow a large Safari visual-viewport lift');
assert.equal(rootStyle.vars['--oa-nav-lift'],'174.0px','content must reserve the same lift');

// A focused textarea + strongly shrunken viewport is a keyboard, not browser chrome.
editing=true;
vv.height=400;
ctx._dockBottomNav();
assert.equal(shift,-174,'soft keyboard must not drag the app nav above the keyboard');
console.log('PASS mobile footer: border-box safe area, cache-busted scripts, live viewport docking, no jitter, keyboard guard');
