const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'static/dashboard.js'),'utf8');
const start=source.indexOf('var _sessionReturnPromise = null;');
const end=source.indexOf('// ── SETTINGS MODAL',start);
const lifecycle=source.slice(start,end);

function harness({me={authenticated:true,wallet:'proven-wallet',csrf_token:'csrf'},blockedStorage=false,disconnected=false,hidden=false,onboardVisible=true}={}){
 let fetches=0,launches=0,applied=[],resumes=0;
 const events={};
 const context={_sessionBootstrapComplete:true,_csrfToken:'',
  localStorage:{getItem(){if(blockedStorage)throw Error('Storage denied');return disconnected?'1':null}},
  document:{visibilityState:hidden?'hidden':'visible',addEventListener:(n,f)=>events[n]=f,
   getElementById:()=>({classList:{contains:()=>!onboardVisible}})},
  window:{addEventListener:(n,f)=>events[n]=f},
  fetch:async()=>{fetches++;return {ok:me!==null,json:async()=>me}},
  _claimPairing:async()=>'',_resumeFromDeviceToken:async()=>{resumes++;return 'restored-wallet'},
  _applySessionWallet:w=>applied.push(w),launchApp:async()=>{launches++},console};
 vm.createContext(context);vm.runInContext(lifecycle,context);
 return {context,events,state:()=>({fetches,launches,applied,resumes})};
}
(async()=>{
 let h=harness();await h.events.visibilitychange();assert.deepEqual(h.state(),{fetches:1,launches:1,applied:['proven-wallet'],resumes:0});
 h=harness({blockedStorage:true});await h.events.online();assert.equal(h.state().launches,1);
 h=harness({me:{authenticated:false}});await h.events.online();assert.deepEqual(h.state().applied,['restored-wallet']);
 h=harness({me:null});await h.events.online();assert.deepEqual(h.state(),{fetches:1,launches:0,applied:[],resumes:0});
 h=harness();await Promise.all([h.events.online(),h.events.visibilitychange()]);assert.equal(h.state().fetches,1,'coalesce simultaneous resume events');
 h=harness({disconnected:true});await h.events.online();assert.equal(h.state().fetches,0,'explicit Disconnect prevents restore');
 h=harness({hidden:true});await h.events.visibilitychange();assert.equal(h.state().fetches,0);
 h=harness({onboardVisible:false});await h.events.online();assert.equal(h.state().launches,0,'do not reinitialize an open dashboard');
 const callback=fs.readFileSync(path.join(root,'templates/phantom_callback.html'),'utf8');
 const a=callback.indexOf('      // Store the same verified recovery credential');
 const b=callback.indexOf('\n    } else {',a);
 const writes=[];
 const cb={wr:{device_token:'verified-token'},localStorage:{setItem:(k,v)=>writes.push([k,v]),removeItem:()=>{}},msg:{},window:{location:{}}};
 vm.runInNewContext(callback.slice(a,b),cb);
 assert.deepEqual(writes,[['orca_device_token','verified-token']]);assert.equal(cb.window.location.href,'/');
 cb.localStorage.setItem=()=>{throw Error('Storage denied')};cb.window.location.href='';
 vm.runInNewContext(callback.slice(a,b),cb);assert.equal(cb.window.location.href,'/','cookie flow survives blocked localStorage');
 assert.equal(source.slice(source.indexOf('(async function initApp'),start).includes('_connectWalletSigned('),false,'startup never prompts for a fresh signature');
 console.log('PASS: resume on return/online, blocked storage, outage, single-flight, Disconnect, background, no reinitialization, Phantom callback persistence');
})().catch(e=>{console.error(e);process.exitCode=1});
