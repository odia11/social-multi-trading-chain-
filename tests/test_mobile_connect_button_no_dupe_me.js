/* Shared across every page (mobile_ui_hotfix.py injects this file
   site-wide). boot() already re-checks auth with /api/me on every load;
   pageshow fires after EVERY load too (not only a bfcache restore), so
   without an event.persisted guard this fired a second, fully redundant
   /api/me on top of what boot() just did -- on every single page view,
   site-wide. A real bfcache restore (persisted=true) still must re-check,
   since the page's auth state may be stale after sitting frozen in cache. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const js=fs.readFileSync('static/mobile-connect-button.js','utf8');

function run(){
  const listeners={window:{}, document:{}};
  let fetchCalls=0;
  // Resolves on the next microtask with a plain guest response, so sync()'s
  // own .finally() clears its `checking` in-flight guard before the test's
  // next await -- a fetch that never settles would make every call after
  // the first look like a false "no duplicate" (still in flight, not skipped).
  const fetchImpl=()=>{fetchCalls++; return Promise.resolve({status:401,ok:false});};
  const el=()=>({style:{},dataset:{},setAttribute(){},remove(){},querySelectorAll:()=>[],querySelector:()=>null});
  const ctx={
    document:{
      readyState:'complete',
      getElementById:()=>null,
      querySelector:()=>null,
      querySelectorAll:()=>[],
      documentElement:el(),
      addEventListener:(name,fn)=>{listeners.document[name]=fn;},
      createElement:()=>el(),
    },
    window:{
      addEventListener:(name,fn)=>{listeners.window[name]=fn;},
      __ORCA_TRUSTED_PHANTOM_PUBLIC_KEY:'',
    },
    localStorage:{getItem:()=>null,setItem(){},removeItem(){}},
    fetch:fetchImpl,
    MutationObserver:class{observe(){}},
    Array, Date, Number, String, RegExp, Promise, console,
  };
  vm.createContext(ctx);
  vm.runInContext(js, ctx);
  return {listeners, calls:()=>fetchCalls};
}

const flush=()=>new Promise((r)=>setImmediate(r));

(async()=>{
  // ---- A plain page load must only ever ask /api/me once, via boot() ----
  let {listeners, calls}=run();
  await flush(); await flush();
  assert.equal(calls(),1,'boot() must check auth exactly once on a normal load');
  assert(listeners.window.pageshow,'a pageshow listener must be registered');

  listeners.window.pageshow({persisted:false});
  await flush(); await flush();
  assert.equal(calls(),1,'pageshow on a fresh load (persisted=false) must NOT re-fetch /api/me -- boot() already just did');

  // ---- A real bfcache restore must still re-check (session may be stale) ----
  listeners.window.pageshow({persisted:true});
  await flush(); await flush();
  assert.equal(calls(),2,'pageshow after an actual bfcache restore (persisted=true) must re-check auth');

  console.log('PASS mobile-connect-button.js: /api/me is fetched once per real page view, and again only on an actual bfcache restore');
})();
