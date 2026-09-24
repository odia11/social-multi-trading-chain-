/* Instagram-style pull-to-refresh on every page: pull down at the top,
   release past the threshold, and the page's data refreshes in place (or,
   on a page with no loader, the page reloads like the browser's own
   pull-to-refresh). It must never capture touches: listeners are passive
   and nothing calls preventDefault, so ordinary swipes only scroll. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const src=fs.readFileSync('static/pull-to-refresh.js','utf8');
const wallet=fs.readFileSync('templates/wallet.html','utf8');
const home=fs.readFileSync('dashboard.html','utf8');
const dash=fs.readFileSync('static/dashboard.js','utf8');
const homeMobile=fs.readFileSync('static/home-mobile.js','utf8');
const mc=fs.readFileSync('static/portfolio-multichain.js','utf8');

assert(!/preventDefault\s*\(/.test(src),'pull-to-refresh must never cancel touches (native scroll/zoom stay untouched)');
for(const ev of ['touchstart','touchmove','touchend']){
  assert(new RegExp("addEventListener\\('"+ev+"'[^]*?\\{passive:true\\}").test(src),ev+' listener must be passive');
}
// A reload is only the fallback for pages without their own loader.
const reloadAt=src.indexOf('location.reload()');
assert(reloadAt>0&&/typeof opts\.onRefresh==='function'\?opts\.onRefresh:function\(\)\{\s*location\.reload\(\)/.test(src),
  'location.reload() may only be the fallback when a page passes no onRefresh');

function run(opts){
  const added=[];
  const ctx={document:{addEventListener:(t)=>added.push(t)},navigator:{},getComputedStyle:()=>({}),setTimeout,Promise,Math,Date,location:{}};
  ctx.window=ctx;vm.createContext(ctx);vm.runInContext(src,ctx);
  ctx.initPullToRefresh(opts);return added.sort();
}
const ALL=['touchcancel','touchend','touchmove','touchstart'];
assert.deepEqual(run(undefined),ALL,'pages without options still get the gesture (reload fallback)');
assert.deepEqual(run({onRefresh:()=>0}),ALL);
assert.deepEqual(run({pull:false,onRefresh:()=>0}),[],'pull:false opts a page out');

// Guards against refreshing while the user is really just scrolling.
assert(src.includes('innerScrolled(e.target)'),'a scrolled inner box under the finger must block a pull');
assert(src.includes('inOverlay(e.target)'),'touches in fixed/sticky layers must never start a pull');
assert(src.includes('customScrollerActive()'),'scrollEl (e.g. an open chat thread) must switch pulling off');
assert(src.includes('opts.ignoreTarget'),'ignoreTarget (e.g. the chat composer) must be honoured');

// Every page that loads the script actually initialises it.
for(const f of fs.readdirSync('templates').filter(f=>f.endsWith('.html'))){
  const t=fs.readFileSync('templates/'+f,'utf8');
  if(t.includes('/static/pull-to-refresh.js'))assert(t.includes('initPullToRefresh('),f+' loads pull-to-refresh.js but never calls it');
}

// Home: loaded before dashboard.js (both deferred, so order holds) and wired
// to the feed plus the mobile Home cards.
assert(home.indexOf('/static/pull-to-refresh.js')>0&&home.indexOf('/static/pull-to-refresh.js')<home.indexOf('/static/dashboard.js'),
  'Home must load pull-to-refresh.js before dashboard.js');
assert(/initPullToRefresh\(\{\s*onRefresh:[^]*loadHomeFeed\(\)[^]*OrcAgentRefreshHome/.test(dash),'Home refresh must reload the feed and the Home cards');
assert(homeMobile.includes('window.OrcAgentRefreshHome=function(){return Promise.allSettled([refreshHomePortfolio(),updateMajorMarkets(),refreshBot()])}'));
for(const f of ['static/navbar.js','static/app-ux.js'])
  assert(fs.readFileSync(f,'utf8').includes('home-mobile.js?v=9'),f+' must cache-bust home-mobile.js');

// Portfolio: one forced-fresh snapshot, then every painter reads it.
assert(/_getPortfolioSnapshot\(true\)/.test(wallet.slice(wallet.indexOf('initPullToRefresh('))),'Portfolio refresh must force one fresh snapshot fetch');
assert(mc.includes('window.OrcAgentRepaintPortfolioTotal=refreshValue;'));
console.log('PASS pull-to-refresh: on every page, passive, reload only as fallback, Home + Portfolio refresh in place');
