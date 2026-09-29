'use strict';
// Mock browser events: follow same-origin history only if an actual previous
// OrcAgent page exists; otherwise let the real anchor navigate to fallback.
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const script=fs.readFileSync('static/launch-back.js','utf8');
function run(referrer,pathname,length){
 let handler=null,backCount=0,prevented=false;
 const el={addEventListener:(type,callback)=>{assert.equal(type,'click');handler=callback}};
 const ctx={document:{getElementById:()=>el,referrer},location:{origin:'https://orcagent.fun',pathname},history:{length,back:()=>backCount++},URL};
 vm.runInNewContext(script,ctx);
 assert.equal(typeof handler,'function');
 handler({preventDefault:()=>{prevented=true}});
 return {backCount,prevented};
}
assert.deepEqual(run('https://orcagent.fun/launches','/token-launch',4),{backCount:1,prevented:true});
for (const value of [
 ['','/token-launch',3],
 ['https://pump.fun/coin/abc','/token-launch',3],
 ['https://orcagent.fun/token-launch','/token-launch',3],
 ['https://orcagent.fun/launches','/token-launch',1],
 ['https://orcagent.fun/token-launch','/launches',1],
]) assert.deepEqual(run(...value),{backCount:0,prevented:false});
console.log('PASS real same-site back when available; direct visits, refresh and external referrers retain safe fallback');
