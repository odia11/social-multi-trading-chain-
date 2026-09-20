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

function postChronologyRegression(){
  const block=js.slice(js.indexOf('/* ── Canonical post deep-links:'),js.indexOf('// ── "new reply on your post" tracking'));
  const ctx={
    location:{hash:'#post-p449'},window:{addEventListener(){}},
    document:{},console,Date,Number,Array
  };
  vm.createContext(ctx);vm.runInContext(block,ctx);
  const recent={id:500,created_at:'2026-09-19 07:18:00'};
  const middle={id:460,created_at:'2026-09-19T06:00:00Z'};
  const old={id:449,created_at:'2026-09-18 07:00:00'};
  const older={id:420,created_at:'2026-09-17T07:00:00+00:00'};
  const ids=items=>Array.from(items,x=>x.id);
  ctx._activeDeepLinkedPost={id:'p449',post:old};
  let initial=[recent,middle];
  assert.deepStrictEqual(ids(ctx._insertLinkedPostChronologically(initial)),[500,460,449],
      'Old linked post follows all newer posts');
  assert.deepStrictEqual(ids(initial),[500,460],'Never reorder shared feed data');
  assert.deepStrictEqual(ids(ctx._insertLinkedPostChronologically([recent,old,older])),[500,449,420],
      'Post already in feed keeps its original position, no duplicate');
  assert.deepStrictEqual(ids(ctx._insertLinkedPostChronologically([recent,middle,older])),[500,460,449,420],
      'More old pages preserve timestamp order');
  ctx._activeDeepLinkedPost={id:'p480',post:{id:480,created_at:'2026-09-19T06:30:00+00:00'}};
  ctx.location.hash='#post-p480';
  assert.deepStrictEqual(ids(ctx._insertLinkedPostChronologically([recent,middle,old])),[500,480,460,449],
      'In-between post goes between newer and older posts');
  ctx.location.hash='';
  assert.deepStrictEqual(ids(ctx._insertLinkedPostChronologically([recent,middle])),[500,460],
      'Normal Home feed unchanged after leaving permalink');
  console.log('PASS linked post chronology: old, duplicate, pagination, mid-feed, normal feed');
}
postChronologyRegression();

(async()=>{
  await run('p449');await run('t456');
  assert(!js.includes('items.unshift(_activeDeepLinkedPost.post)'), 'Never move old posts above new ones');
  assert(!js.includes('_homeFeedData.unshift(d.post)'), 'Never move fetched post to feed top');
  assert(js.includes('items = _insertLinkedPostChronologically(items)'), 'Render target chronologically');
  console.log('PASS deep-linked posts preserve chronological feed order');
  const dm=fs.readFileSync('templates/messages.html','utf8');
  const group=fs.readFileSync('templates/group_detail.html','utf8');
  assert(dm.includes('_dmPostLinkText(m.message)'));
  assert(group.includes('_renderMentionText(textContent)') && group.includes('View post on OrcAgent →'));
  console.log('PASS DM and community post links clickable');
})().catch(e=>{console.error(e);process.exit(1)});
