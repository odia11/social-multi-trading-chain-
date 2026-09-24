/* Portfolio gets Instagram-style pull-to-refresh: pull down at the top of
   the page, release past the threshold, and everything on it refreshes in
   place. It's opt-in (pull:true) so no other page changes behaviour, and it
   must never capture touches or reload the page -- swipes elsewhere only
   scroll. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const src=fs.readFileSync('static/pull-to-refresh.js','utf8');
const wallet=fs.readFileSync('templates/wallet.html','utf8');
const mc=fs.readFileSync('static/portfolio-multichain.js','utf8');

assert(!/preventDefault\s*\(/.test(src),'pull-to-refresh must never cancel touches (native scroll/zoom stay untouched)');
assert(!/location\.reload|location\.href\s*=/.test(src),'pull-to-refresh refreshes data in place, never reloads the page');
for(const ev of ['touchstart','touchmove','touchend']){
  assert(new RegExp("addEventListener\\('"+ev+"'[^]*?\\{passive:true\\}").test(src),ev+' listener must be passive');
}

// Opt-in: pages that call it without pull:true (every page but Portfolio)
// must not get any touch listeners at all.
function run(opts){
  const added=[];
  const ctx={window:{},document:{addEventListener:(t)=>added.push(t)},navigator:{},getComputedStyle:()=>({}),setTimeout,Promise,Math,Date};
  ctx.window=ctx;vm.createContext(ctx);vm.runInContext(src,ctx);
  ctx.initPullToRefresh(opts);return added;
}
assert.deepEqual(run(undefined),[],'initPullToRefresh() without options must stay a no-op');
assert.deepEqual(run({onRefresh:()=>0}),[],'onRefresh alone (no pull:true) must stay a no-op');
assert.deepEqual(run({pull:true,onRefresh:()=>0}).sort(),['touchcancel','touchend','touchmove','touchstart']);

assert(/initPullToRefresh\(\{\s*pull:\s*true,/.test(wallet),'Portfolio must opt in with pull:true');
assert(/_getPortfolioSnapshot\(true\)/.test(wallet.slice(wallet.indexOf('initPullToRefresh({ pull'))),
  'Portfolio refresh must force one fresh snapshot fetch');
assert(mc.includes('window.OrcAgentRepaintPortfolioTotal=refreshValue;'),'multichain must expose an unambiguous total repaint');
const others=fs.readdirSync('templates').filter(f=>f!=='wallet.html'&&f.endsWith('.html'))
  .filter(f=>/initPullToRefresh\(\{\s*pull:\s*true/.test(fs.readFileSync('templates/'+f,'utf8')));
assert.deepEqual(others,[],'only Portfolio opts in for now');
console.log('PASS Portfolio pull-to-refresh: opt-in, passive, no reload, forced fresh snapshot');
