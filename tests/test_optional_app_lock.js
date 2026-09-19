const fs=require('fs'),vm=require('vm'),assert=require('assert');
const js=fs.readFileSync('static/dashboard.js','utf8');
const html=fs.readFileSync('dashboard.html','utf8');
const start=js.indexOf('/* ── Optional per-account app-screen lock');
const end=js.indexOf('async function _loginWithPassword(){',start);
assert(start>=0&&end>start);
const block=js.slice(start,end);
const flush=()=>new Promise(r=>setImmediate(r));
async function setup(){
  let hiddenCb,pageshowCb,challengeCount=0,assertions=0,authResult='wallet-a';
  const elements={};
  for(const name of ['oa-app-lock','oa-app-lock-msg','oa-app-lock-btn','st-app-lock-row','st-app-lock-toggle','st-app-lock-status','app']){
    elements[name]={
      style:{display:name==='oa-app-lock'?'none':''},
      attrs:new Set(),setAttribute(k){this.attrs.add(k)},removeAttribute(k){this.attrs.delete(k)},
      getAttribute(k){return this.attrs.has(k)?'':null},textContent:'',checked:false,disabled:false
    };
  }
  const prefs={'wallet-a':true,'wallet-b':false};
  const storage={};
  const calls=[];
  const ctx={
    console,Date,Promise,Number,setInterval(){return 1},clearInterval(){},
    phantomKey:'wallet-a',guestMode:false,_csrfToken:'csrf',
    localStorage:{
      getItem:k=>storage[k]??null,setItem:(k,v)=>storage[k]=v
    },
    window:{addEventListener:(name,fn)=>{if(name==='pageshow')pageshowCb=fn}},
    document:{
      visibilityState:'visible',getElementById:name=>elements[name]||null,
      addEventListener:(name,fn)=>{if(name==='visibilitychange')hiddenCb=fn}
    },
    _pkLoginBusy:false,_pkLoginOpts:null,_pkLoginAt:0,PK_OPTS_FRESH_MS:80000,
    _prefetchPasskeyLoginOptions:async function(){challengeCount++;ctx._pkLoginAt=Date.now();
      return ctx._pkLoginOpts={challenge:'available',allowCredentials:undefined}},
    _waOptionsFromJSON:x=>x,_waCredentialToJSON:()=>({id:'own-key'}),
    navigator:{credentials:{get:async()=>{assertions++;return {id:'own-key'}}}},
    _handleNotifDeepLink(){},
    location:{hash:'#post-p449'},
    fetch:async (url,opts)=>{
      calls.push([url,opts]);
      if(url==='/api/auth/app-lock' && (!opts||!opts.method))
        return {ok:true,json:async()=>({ok:true,enabled:prefs[ctx.phantomKey],has_passkey:true})};
      if(url==='/api/auth/app-lock' && opts.method==='POST'){
        assert.equal(opts.headers['X-CSRF-Token'],'csrf');
        assert.equal(opts.credentials,'include');
        prefs[ctx.phantomKey]=JSON.parse(opts.body).enabled;
        return {ok:true,json:async()=>({ok:true,enabled:prefs[ctx.phantomKey],has_passkey:true})};
      }
      if(url==='/api/auth/app-lock/unlock'){
        assert.equal(opts.headers['X-CSRF-Token'],'csrf');
        return {ok:authResult===ctx.phantomKey,json:async()=>authResult===ctx.phantomKey
          ? ({ok:true,wallet:authResult}) : ({ok:false,msg:'Wrong account'})};
      }
      throw Error(url);
    }
  };
  vm.createContext(ctx);vm.runInContext(block,ctx);
  return {ctx,elements,prefs,storage,calls,hiddenCb,pageshowCb,
    setResult:x=>authResult=x,assertions:()=>assertions,challenges:()=>challengeCount};
}
(async()=>{
  assert(html.includes('id="st-app-lock-toggle"'));
  assert(html.includes('id="oa-app-lock"'));
  const {ctx,elements,prefs,storage,hiddenCb,pageshowCb,setResult,assertions}=await setup();
  assert(!ctx._appLockEnabled,'off unless account preference says otherwise');
  await ctx._appLockLoad(false);
  assert.equal(elements['oa-app-lock'].style.display,'none','Settings must not lock current screen');
  assert.equal(ctx._appLockEnabled,true);
  await ctx._appLockLoad(true);
  assert.equal(elements['oa-app-lock'].style.display,'flex','Startup must lock when enabled');
  assert(elements.app.attrs.has('inert'),'Underlying UI must not accept input');
  setResult('wallet-b');
  await ctx._unlockOrcAgent();
  assert.equal(elements['oa-app-lock'].style.display,'flex','Other user passkey cannot unlock account');
  setResult('wallet-a');
  await ctx._unlockOrcAgent();
  assert.equal(elements['oa-app-lock'].style.display,'none','Verified same-account passkey unlocks');
  assert.equal(ctx.phantomKey,'wallet-a','Must not disconnect or switch wallet');
  assert(!elements.app.attrs.has('inert'),'Restore input on unlock');
  assert.equal(assertions(),2);
  ctx.document.visibilityState='hidden';hiddenCb();
  assert.equal(elements['oa-app-lock'].style.display,'flex','Background must mask account instantly');
  ctx.document.visibilityState='visible';hiddenCb();
  assert.equal(elements['oa-app-lock'].style.display,'flex');
  await ctx._setAppLockPreference(false);
  assert.equal(elements['oa-app-lock'].style.display,'none');
  assert.equal(prefs['wallet-a'],false,'Opt-out persists to server');
  assert.equal(storage['orca_app_lock_wallet-a'],'0');
  ctx.phantomKey='wallet-b';
  await ctx._appLockLoad(true);
  assert.equal(ctx._appLockEnabled,false,'Per-account preference never leaks to second user');
  ctx.phantomKey='wallet-a';
  pageshowCb({persisted:true});
  assert.equal(elements['oa-app-lock'].style.display,'none','Disabled lock does not appear on BFCache');
  console.log('PASS optional app lock: default off, Settings safe, startup/background gate, account-bound WebAuthn, opt out, wallet isolation, no logout');
})().catch(e=>{console.error(e);process.exit(1)});
