const fs=require('fs'),vm=require('vm'),assert=require('assert');
const js=fs.readFileSync('static/dashboard.js','utf8');
const start=js.indexOf('var _pkLoginOpts = null');
const stop=js.indexOf('async function _loginWithPassword()',start);
assert(start>=0 && stop>start);
const funcs=js.slice(start,stop);
const onboarding=js.slice(js.indexOf("document.addEventListener('DOMContentLoaded',function(){",js.indexOf('/* On load: switch connect screen')),
                          js.indexOf('// ── CSRF TOKEN',js.indexOf('/* On load: switch connect screen')));
const flush=()=>new Promise(r=>setImmediate(r));
async function scenario(ua,stored){
  const els={};
  for(const id of ['ob-bio-btn','ob-bio-label','ob-bio-err','ob-alt-link','ob-pwd-form','ob-wallet-btns','phantom-ob-btn','ob-phantom-note','solflare-ob-btn','ob-skip-btn','onboard'])
    els[id]={style:{display:''},textContent:'',disabled:false,classList:{contains(){return false}}};
  const requests=[];
  let getResolve=null, timer=null, reloads=0, getCalls=0;
  const local={getItem(k){return k==='orca_credential_id'?stored:null},setItem(k,v){this.saved=v}};
  const cred={id:'registered-credential',rawId:new Uint8Array([1,2]).buffer,response:{}};
  const ctx={
    console,Date,Promise,Uint8Array,navigator:{userAgent:ua,credentials:{
      get(options){getCalls++;assert(options.publicKey.challenge,'Challenge missing');
        assert(!options.publicKey.allowCredentials,'Passkey discovery must not be limited to localStorage ID');
        return new Promise(r=>getResolve=r);}
    }},
    window:{PublicKeyCredential:function(){}},
    location:{reload(){reloads++}},
    localStorage:local,
    document:{getElementById:id=>els[id],addEventListener(name,fn){ctx.boot=fn}},
    _faceIdPossible:()=>Promise.resolve(true),
    _csrfToken:'test-csrf',
    _applyPhantomDetection(){},_applySolflareDetection(){},
    _showWalletOptions(){},
    _waOptionsFromJSON:x=>x,
    _waCredentialToJSON:x=>({id:x.id,type:'public-key'}),
    fetch:async (url,opts)=>{
      requests.push({url,opts});
      if(url.includes('/options'))return {ok:true,json:async()=>({challenge:'safe-challenge'})};
      assert.equal(url,'/api/auth/webauthn/login');
      assert.equal(opts.method,'POST');
      assert.equal(opts.credentials,'include');
      assert.equal(opts.headers['X-CSRF-Token'],'test-csrf');
      return {ok:true,json:async()=>({success:true})};
    },
    setInterval(fn){timer=fn;return 1},clearInterval(){},setTimeout(){},
    PK_OPTS_FRESH_MS:80000
  };
  vm.createContext(ctx);vm.runInContext(funcs+onboarding,ctx);
  ctx.boot();
  await flush();await flush();
  const expected=/Android/.test(ua)?'Unlock with fingerprint or screen lock':'Unlock with Face ID';
  assert.equal(els['ob-bio-label'].textContent,expected);
  assert.equal(els['ob-bio-btn'].style.display,'flex');
  assert.equal(els['ob-wallet-btns'].style.display,stored?'none':'block');
  assert.equal(requests[0].url,'/api/auth/webauthn/login/options');
  ctx._webAuthnLogin();
  await flush();
  assert.equal(getCalls,1,'Native prompt should open');
  const before=requests.length;timer();
  assert.equal(requests.length,before,'Do not refresh challenge while prompt is active');
  getResolve(cred);
  await flush();await flush();
  assert.equal(reloads,1,'Only verified login reloads');
  assert.equal(local.saved,cred.id);
  assert.equal(els['ob-bio-label'].textContent,expected);
  console.log('PASS',ua,'storage:',stored||'missing','discoverable passkey + verified login + no prompt race');
}
(async()=>{
  await scenario('Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X)','old-credential-id');
  await scenario('Mozilla/5.0 (Linux; Android 16; Pixel 9)','');
  assert(!js.includes("localStorage.setItem('orca_credential_id','1')"));
  console.log('PASS fake credential sentinel removed');
})().catch(e=>{console.error(e);process.exit(1)});

// Verify Settings route and the REAL registration POST's CSRF/session wiring.
(async function registrationScenario(){
  const page=fs.readFileSync('dashboard.html','utf8');
  assert(page.includes('id="st-passkey-settings"'));
  assert(page.includes('onclick="_setupSettingsPasskey()"'));
  assert(js.includes("_prepareSettingsPasskey();"));
  const server=fs.readFileSync('dashboard.py','utf8');
  const regStart=server.indexOf('def webauthn_register_options():');
  const authStart=server.indexOf('def webauthn_login():');
  assert(server.slice(regStart,authStart).includes('user_verification=_WaUserVerificationRequirement.REQUIRED'));
  assert(server.slice(regStart,authStart).includes('resident_key=_WaResidentKeyRequirement.REQUIRED'));
  assert(server.slice(authStart,authStart+2300).includes('require_user_verification=True'));
  console.log('PASS server requires verified, discoverable device passkeys');

  const begin=js.indexOf('async function _setupFaceID(opts){');
  const end=js.indexOf('async function _removeFaceId(){',begin);
  assert(begin>=0 && end>begin);
  const events=[];
  const btn={disabled:false,textContent:'Set up passkey'};
  const msg={style:{},textContent:''};
  let callback=false;
  const cred={id:'created-credential',rawId:new Uint8Array([5]).buffer,response:{}};
  const ctx={
    Promise,Date,console,phantomKey:'verified-wallet',
    _platformPasskeyStatus:true,_pkBusy:false,
    _pkOpts:{challenge:'fresh-challenge'},_pkOptsAt:Date.now(),
    _pkOptsFresh:()=>true,_prefetchPasskeyOptions:()=>Promise.resolve({challenge:'fresh-challenge'}),
    _waOptionsFromJSON:x=>x,
    _waCredentialToJSON:()=>({id:cred.id}),
    _keepPasskeyOptionsFresh(){},_updateFaceIdStatus(){},
    _faceIdPossible:()=>{throw new Error('Capability must be prefetched before tapping')},
    _csrfToken:'csrf-value',
    window:{PublicKeyCredential:function(){}},
    navigator:{credentials:{create:async x=>{events.push('prompt');return cred}}},
    localStorage:{setItem(){}},
    document:{getElementById:()=>null},
    setTimeout(){},
    fetch:async (url,opts)=>{
      events.push(url);
      assert.equal(url,'/api/auth/webauthn/register');
      assert.equal(opts.credentials,'include');
      assert.equal(opts.headers['X-CSRF-Token'],'csrf-value');
      return {json:async()=>({success:true})};
    }
  };
  vm.createContext(ctx);vm.runInContext(js.slice(begin,end),ctx);
  await ctx._setupFaceID({btn,msg,btnLabel:'Set up passkey',onDone(){callback=true}});
  assert.equal(events[0],'prompt','Native biometric prompt comes from the user tap');
  assert.equal(events[1],'/api/auth/webauthn/register');
  assert(callback,'Registration success calls completion callback');
  assert(msg.textContent.includes('Passkey saved'));
  console.log('PASS Settings registration: immediate native prompt, verified POST, CSRF/session');
})().catch(e=>{console.error(e);process.exitCode=1});
