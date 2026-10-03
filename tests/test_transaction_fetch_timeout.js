const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const root=path.join(__dirname,'..');
function wrapper(file){
 const s=fs.readFileSync(path.join(root,file),'utf8'), i=s.indexOf('DEFAULT_FETCH_TIMEOUT_MS');
 return s.slice(s.lastIndexOf('(function(){',i),s.indexOf('})();',i)+5);
}
async function test(files){
 let timers=[],calls=[],resolve;
 const ctx={AbortController,Request,FormData,setTimeout:(fn,ms)=>{timers.push({fn,ms});return timers.length},clearTimeout:()=>{}};
 ctx.window={fetch:(input,init)=>{calls.push(init);return new Promise(r=>resolve=r)}};
 vm.createContext(ctx);files.forEach(f=>vm.runInContext(wrapper(f),ctx));
 for(const url of ['/api/wallet/convert','/api/wallet/sol-swap/execute','/api/wallet/send','/api/wallet/send-token','/api/tip']){
  timers=[];const before=calls.length,p=ctx.window.fetch(url,{method:'POST'});
  assert.equal(timers.length,1);assert.equal(timers[0].ms,180000);
  assert.equal(calls.length,before+1);assert(!calls.at(-1).signal.aborted);
  resolve({ok:true});await p;
 }
 timers=[];const p=ctx.window.fetch('/api/wallet/tokens');
 assert.equal(timers[0].ms,15000);timers[0].fn();assert(calls.at(-1).signal.aborted);resolve({});await p;
 timers=[];const ctl=new AbortController(),q=ctx.window.fetch('/api/tip',{method:'POST',signal:ctl.signal});
 assert.equal(timers.length,0);assert.strictEqual(calls.at(-1).signal,ctl.signal);resolve({});await q;
 timers=[];const r=ctx.window.fetch(new Request('https://orcagent.fun/api/tip',{method:'POST'}));
 assert.equal(timers[0].ms,180000);resolve({});await r;
}
(async()=>{await test(['static/navbar.js']);await test(['static/dashboard.js']);await test(['static/navbar.js','static/dashboard.js']);await test(['static/dashboard.js','static/navbar.js']);console.log('PASS: slow transaction requests, GET aborts, caller signals, Request objects, both wrapper orders, no retries')})().catch(e=>{console.error(e);process.exitCode=1});
