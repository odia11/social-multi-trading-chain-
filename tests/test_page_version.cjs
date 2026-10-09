// A restored document must compare its own build, not adopt the server build.
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=process.env.BASELINE
  ?require('child_process').execFileSync('git',['show','HEAD:static/dashboard.js'],{encoding:'utf8'})
  :fs.readFileSync('static/dashboard.js','utf8');
const code=source.slice(source.indexOf('// ── VERSION POLLING'),source.indexOf('// ── TOKEN INCINERATOR'));
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function run(build,server){
  const banner={style:{}},events={},requests=[];let poll;
  const document={hidden:false,querySelector:()=>build?{content:build}:null,
    getElementById:()=>banner,addEventListener:(name,fn)=>events[name]=fn};
  const context={document,OrcPageLifecycle:{setInterval:fn=>poll=fn},
    fetch:async(url,options)=>{requests.push(options);return {ok:true,json:async()=>({version:server})}}};
  vm.runInNewContext(code,context);await flush();
  return {banner,events,requests,document,poll,setServer:v=>server=v};
}
(async()=>{
  const stale=await run('old-build','new-build');
  assert.equal(stale.banner.style.display,'flex','stale PWA must detect deployment on first request');
  assert.equal(stale.requests[0].cache,'no-store');
  const current=await run('current-build','current-build');
  assert.notEqual(current.banner.style.display,'flex');
  current.setServer('next-build');
  current.document.hidden=true;await current.poll();
  assert.equal(current.requests.length,1,'hidden document should not poll');
  current.document.hidden=false;current.events['orca:lifecycle-resume']();await flush();
  assert.equal(current.banner.style.display,'flex','foreground resume checks immediately');
  const legacy=await run(null,'same-build');await legacy.poll();
  assert.notEqual(legacy.banner.style.display,'flex','older markup without meta keeps its baseline');
  console.log('PASS document build, initial mismatch, fresh request, hidden polling, resume and missing-meta fallback');
})().catch(e=>{console.error(e);process.exit(1)});
