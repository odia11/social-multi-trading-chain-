/* Simulated profile DOM: no network, wallet transfers or real browser. */
'use strict';
const fs=require('fs');
const vm=require('vm');
const assert=require('assert');
const source=fs.readFileSync('static/tip-experience.js','utf8');
const nodes={};
for(const id of ['oa-profile-balance-value','oa-profile-balance-available',
                 'oa-profile-balance-other']){
  nodes[id]={textContent:''};
}
const cssClasses=new Set();
nodes['oa-profile-balance']={
  dataset:{userId:'42'},classList:{
    toggle:(name,yes)=>yes?cssClasses.add(name):cssClasses.delete(name),
    add:(name)=>cssClasses.add(name)
  }
};
const doc={
  hidden:false,readyState:'loading',
  getElementById:(id)=>nodes[id]||null,
  addEventListener:()=>{}
};
let response={ok:true,user_id:42,portfolio_value_usdc_approx:0.106,
  available_usdc:0,other_assets_usdc_approx:0.106,
  generated_at:1780000000,stale:false};
let networkError=false;
const win={addEventListener:()=>{}};
vm.runInNewContext(source,{
  window:win,document:doc,location:{pathname:'/profile/42'},
  fetch:async()=>networkError?Promise.reject(Error('RPC offline')):{ok:true,json:async()=>response}
});
(async()=>{
 await win.OrcAgentRefreshProfileBalance();
 assert(nodes['oa-profile-balance-value'].textContent.includes('0.106 USDC'));
 assert.strictEqual(nodes['oa-profile-balance-available'].textContent,'0.00 USDC');
 assert(nodes['oa-profile-balance-other'].textContent.includes('0.106 USDC'));
 assert(!source.includes('oa-profile-balance-state'));
 assert(source.includes('},15000);'));
 console.log('PASS market value and actual USDC remain distinct; refresh stays background-only');

 networkError=true;
 await win.OrcAgentRefreshProfileBalance();
 assert(nodes['oa-profile-balance-value'].textContent.includes('0.106 USDC'));
 assert(nodes['oa-profile-balance-value'].textContent.includes('0.106 USDC'));
 console.log('PASS RPC failure preserves last known real balance without status text');

 networkError=false;response={...response,user_id:999,portfolio_value_usdc_approx:50};
 await win.OrcAgentRefreshProfileBalance();
 assert(nodes['oa-profile-balance-value'].textContent.includes('0.106 USDC'));
 console.log('PASS wrong profile response cannot overwrite visible balance');
 console.log('ALL LIVE PROFILE BALANCE UI REGRESSIONS PASSED');
})().catch(e=>{console.error(e);process.exitCode=1});
