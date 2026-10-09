const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright');
const root=path.resolve(__dirname,'..');
const all=process.env.BASELINE?require('child_process').execFileSync('git',['show','HEAD:static/dashboard.js'],{cwd:root,encoding:'utf8'}):fs.readFileSync(root+'/static/dashboard.js','utf8');
const code=all.slice(all.indexOf('var _feedAvatarScope=null;'),all.indexOf('function _reconcileFeedCards('));
(async()=>{
 const b=await chromium.launch({executablePath:process.env.ORCAGENT_CHROMIUM,args:['--no-sandbox']});
 try{
 for(const width of [390,1280]){
  const p=await b.newPage({viewport:{width,height:844}});let calls=0;
  await p.route('http://avatar.test/**',async r=>{
   if(r.request().url().includes('/avatar/photo/')){
    calls++;if(calls===1)return r.fulfill({status:503,body:'temporary failure'});
    return r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><rect width="40" height="40" fill="gold"/></svg>'});
   }
   return r.fulfill({contentType:'text/html',body:'<!doctype html><body></body>'});
  });
  await p.goto('http://avatar.test/');
  await p.addScriptTag({content:fs.readFileSync(root+'/static/page-lifecycle.js','utf8')});
  await p.addScriptTag({content:code});
  await p.evaluate(()=>{
   document.body.innerHTML='<article id="old"><div class="fc-avatar" style="width:44px;height:44px;position:relative"><span>O</span><img src="/avatar/photo/one?v=original" style="width:44px;height:44px" onerror="_feedAvatarFailed(this)" onload="_feedAvatarLoaded(this)"></div></article>';
   window.original=document.querySelector('img');_initFeedAvatars(document);
  });
  await p.waitForFunction(()=>original.naturalWidth>0&&original.style.display!=='none');
  assert.equal(calls,2);
  assert.equal(await p.evaluate(()=>original===document.querySelector('img')),true);
  // Content edits retain the successfully recovered original image even though
  // its actual retry URL differs from the canonical profile-photo URL.
  await p.evaluate(()=>{
   const fresh=document.createElement('article');fresh.innerHTML='<div class="fc-avatar"><img src="/avatar/photo/one?v=original"></div>';
   _reuseFeedMedia(document.getElementById('old'),fresh);
   document.body.replaceChildren(fresh);_initFeedAvatars(document);
  });
  assert.equal(await p.evaluate(()=>original===document.querySelector('img')&&original.style.display!=='none'),true);
  // A request that never emits load/error was not handled by the old fix.
  // Put a lazy photo outside the viewport: initialization must start it now.
  let stalledRequests=0;const held=[];
  await p.route('http://avatar.test/avatar/photo/stalled*',r=>{
    stalledRequests++;
    if(!r.request().url().includes('avatar_retry')){held.push(r);return;}
    return r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><rect width="40" height="40" fill="gold"/></svg>'});
  });
  await p.evaluate(()=>{
    _FEED_AVATAR_LOAD_TIMEOUT=250;
    document.body.insertAdjacentHTML('beforeend','<div class="fc-avatar" style="position:relative;margin-top:5000px;width:44px;height:44px"><img id="stalled" loading="lazy" src="/avatar/photo/stalled?v=1" style="position:absolute;width:44px;height:44px"></div>');
    window.stalled=document.getElementById('stalled');_initFeedAvatars(document);
  });
  await p.waitForFunction(()=>stalled.naturalWidth>0&&stalled.style.display!=='none',null,{timeout:2500});
  assert.equal(stalledRequests,2);assert.equal(await p.evaluate(()=>stalled===document.getElementById('stalled')),true);
  assert.equal(await p.evaluate(()=>stalled.loading),'eager');
  await p.evaluate(()=>{stalled.style.display='none';document.dispatchEvent(new Event('orca:lifecycle-resume'));});
  assert.equal(await p.evaluate(()=>stalled.style.display),'');
  await p.evaluate(()=>_FEED_AVATAR_LOAD_TIMEOUT=6000);
  for(const r of held)await r.abort().catch(()=>{});
  // A permanent failure is bounded; online recovery can try again.
  await p.route('http://avatar.test/avatar/photo/broken*',r=>r.fulfill({status:404,body:''}));
  await p.evaluate(()=>{document.body.insertAdjacentHTML('beforeend','<div class="fc-avatar"><img id="bad" src="/avatar/photo/broken"></div>');_initFeedAvatars(document);});
  await p.waitForFunction(()=>document.getElementById('bad').dataset.feedAvatarRetries==='2'&&!document.getElementById('bad')._feedAvatarTimer);
  const n=await p.evaluate(()=>document.getElementById('bad').dataset.feedAvatarRetries);
  await p.waitForTimeout(1000);assert.equal(await p.evaluate(()=>document.getElementById('bad').dataset.feedAvatarRetries),n);
  await p.evaluate(()=>dispatchEvent(new Event('online')));
  assert.equal(await p.evaluate(()=>document.getElementById('bad').dataset.feedAvatarRetries),'1');
  await p.evaluate(()=>_feedAvatarScope.cleanup('test'));
  assert.equal(await p.evaluate(()=>document.getElementById('bad')._feedAvatarTimer),null);
  await p.close();console.log('PASS '+width+': failed AND stalled photos recover without replacing DOM; eager offscreen avatar, resume visibility, retained media, bounded retries and cleanup');
 }
 }finally{await b.close()}
})().catch(e=>{console.error(e);process.exit(1)});
