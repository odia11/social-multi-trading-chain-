const fs=require('fs');
const vm=require('vm');
const assert=require('assert');

const handlers={};
let networkFetches=0;
let cacheWrites=0;

const context={
  console,
  URL,
  Request,
  Response,
  Headers,
  Map,
  Promise,
  Date,
  setTimeout,
  clearTimeout,
  fetch:async function(req){
    networkFetches++;
    const url=typeof req==='string'?req:req.url;
    return new Response('<!doctype html><html><body>'+url+'</body></html>',{
      status:200,
      headers:{'content-type':'text/html; charset=utf-8','cache-control':'private, no-store'}
    });
  },
  caches:{
    open:async function(){
      return {
        add:async function(){},
        match:async function(){return null},
        put:async function(){cacheWrites++;}
      };
    },
    keys:async function(){return[]},
    delete:async function(){return true}
  },
  self:{
    location:{origin:'https://orcagent.fun'},
    clients:{claim:async function(){}},
    skipWaiting:async function(){},
    registration:{showNotification:async function(){}},
    addEventListener:function(type,fn){handlers[type]=fn;}
  },
  clients:{
    matchAll:async function(){return[]},
    openWindow:async function(){}
  }
};
context.globalThis=context;
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/sw.js','utf8'),context,{filename:'sw.js'});

assert.ok(handlers.message,'message handler registered');
assert.ok(handlers.fetch,'fetch handler registered');

async function warm(url,clientId='client-1'){
  let pending=Promise.resolve();
  handlers.message({
    data:{type:'oa-nav-prefetch',url},
    source:{id:clientId},
    waitUntil:function(p){pending=p;}
  });
  await pending;
}
async function navigate(url,clientId='client-1'){
  let responsePromise=null;
  const request={
    method:'GET',
    mode:'navigate',
    url:'https://orcagent.fun'+url,
    clone:function(){return this;}
  };
  handlers.fetch({
    request,
    clientId,
    resultingClientId:'',
    respondWith:function(p){responsePromise=Promise.resolve(p);},
    waitUntil:function(){}
  });
  assert.ok(responsePromise,'navigation was intercepted');
  return responsePromise;
}

(async function(){
  await warm('/profile/alice');
  assert.equal(networkFetches,1,'intent performs one early network read');

  const response=await navigate('/profile/alice');
  assert.equal(response.status,200);
  assert.ok((await response.text()).includes('/profile/alice'));
  assert.equal(networkFetches,1,'native navigation reuses warmed document instead of refetching');
  assert.equal(cacheWrites,0,'authenticated navigation HTML never enters Cache Storage');

  await warm('/api/me');
  assert.equal(networkFetches,1,'API routes are never warmed as documents');

  await warm('/phantom-callback?x=1');
  assert.equal(networkFetches,1,'Phantom callback routes are never warmed');

  await warm('https://evil.example/profile/alice');
  assert.equal(networkFetches,1,'cross-origin routes are never warmed');

  await warm('/x/connect');
  assert.equal(networkFetches,1,'unknown or side-effect GET routes are never warmed');

  const cold=await navigate('/profile/bob','client-2');
  assert.equal(cold.status,200);
  assert.equal(networkFetches,2,'cold navigation falls back to normal network fetch');

  console.log('PASS X-style navigation reuses one ephemeral per-client document');
  console.log('PASS authenticated HTML is RAM-only and never written to Cache Storage');
  console.log('PASS API, callback, cross-origin and non-allowlisted GET routes are excluded');
})().catch(function(err){console.error(err);process.exit(1);});
