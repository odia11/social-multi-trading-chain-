const assert=require('assert');
const fs=require('fs');
const vm=require('vm');
const js=fs.readFileSync('static/dashboard.js','utf8');
const block=js.slice(js.indexOf('/* ── Canonical post deep-links:'),js.indexOf('// ── "new reply on your post" tracking'));
assert(block.includes('function _jumpToPost'));
async function run(id){
  let app={style:{display:'none'}}, card=null, scrolled=0, requested=[], posts=0;
  const doc={
    getElementById(name){if(name==='app')return app;if(name==='dash-wallet')return {style:{display:'none'}};if(name==='fc-card-'+id)return card;return null},
    contains(node){return node===card}
  };
  const ctx={
    window:{addEventListener(){}},document:doc,location:{hash:'#post-'+id,origin:'https://orcagent.fun',pathname:'/'},
    history:{replaceState(){},pushState(){}},
    _dmOpen:false,_gcOpen:false,_homeFeedData:[],_feedPostById:{},
    sessionStorage:{getItem(){return null},removeItem(){}},console,
    fetch:async path=>{requested.push(path);return {ok:true,json:async()=>({ok:true,post:id[0]==='p'?{id:Number(id.slice(1)),type:'text',content:'Hello'}:{trade_id:Number(id.slice(1)),type:'trade'}})}},
    renderHomeFeed(){posts++;card={dataset:{},classList:{add(){},remove(){}},querySelector(){return null},scrollIntoView(opts){scrolled++;assert.equal(opts.behavior,'auto')}}},
    _feedLoadReplies(){},_fcMarkRepliesSeen(){},_sbNav(){},
    requestAnimationFrame(cb){cb()},setTimeout(){},Promise,Date
  };
  vm.createContext(ctx);vm.runInContext(block,ctx);
  ctx._handleNotifDeepLink();
  assert.equal(requested.length,0,'Must not treat hidden app as opened');
  assert.equal(ctx._lastDeepLinkHash,null);
  app.style.display='block';
  ctx._handleNotifDeepLink();
  await new Promise(r=>setImmediate(r));
  await new Promise(r=>setImmediate(r));
  assert.equal(requested[0],'/api/feed/post/'+id,'Must fetch exact post');
  assert.equal(scrolled,1,'Must land directly on the post');
  assert.equal(ctx._lastDeepLinkHash,'#post-'+id,'Mark handled only when visible');
  assert.equal(ctx._activeDeepLinkedPost.id,id,'Pin exact post');
  assert.equal(posts,1,'Render exact post');
  ctx._handleNotifDeepLink();
  await new Promise(r=>setImmediate(r));
  assert.equal(scrolled,1,'Do not reopen already visible post');
  console.log('PASS instant exact post',id);
}
(async()=>{
  await run('p449');await run('t456');
  assert(js.includes("items.unshift(_activeDeepLinkedPost.post)"),'Keep post across feed refresh/filter');
  assert(js.includes("if(_activeDeepLinkedPost && location.hash === '#post-'+_activeDeepLinkedPost.id)"),'Keep post in feed loads');
  console.log('PASS deep-linked posts survive feed pagination/filter/refresh');
  const dm=fs.readFileSync('templates/messages.html','utf8');
  const group=fs.readFileSync('templates/group_detail.html','utf8');
  assert(dm.includes('_dmPostLinkText(m.message)'));
  assert(group.includes('_renderMentionText(textContent)') && group.includes('View post on OrcAgent →'));
  console.log('PASS DM and community post links clickable');
})().catch(e=>{console.error(e);process.exit(1)});
