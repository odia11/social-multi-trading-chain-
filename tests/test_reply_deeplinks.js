const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const src=fs.readFileSync('static/dashboard.js','utf8');
const code=src.slice(src.indexOf('/* ── Canonical post deep-links:'),src.indexOf('// ── "new reply on your post" tracking'));
(async()=>{
 let loaded=0,postScroll=0,replyScroll=0;
 const app={style:{display:'block'}};
 const rbox={dataset:{},classList:{add(c){this[c]=true}}};
 const target={classList:{add(c){this[c]=true},remove(){}},scrollIntoView(){assert.ok(loaded);replyScroll++}};
 const card={dataset:{},classList:{add(){},remove(){}},scrollIntoView(){postScroll++},querySelector(){return null}};
 const ctx={console,URL,Promise,Date,Number,
 window:{addEventListener(){}},location:{origin:'https://orcagent.fun',pathname:'/',hash:'#post-p1-reply-42'},
 history:{pushState(_,__,url){ctx.location.hash=new URL(url,ctx.location.origin).hash},replaceState(){}},
 document:{getElementById(id){return {app,'fc-card-p1':card,'rbox-p1':rbox}[id]||null},contains:n=>n===card,querySelector:s=>s.includes('42')?target:null},
 _dmOpen:false,_gcOpen:false,_feedPostById:{p1:{id:1}},renderHomeFeed(){},
 sessionStorage:{value:null,setItem(_,v){this.value=v},getItem(){return this.value},removeItem(){this.value=null}},
 _feedLoadReplies:async()=>{await Promise.resolve();loaded++},_fcMarkRepliesSeen(){},requestAnimationFrame:f=>f(),setTimeout(){}};
 vm.createContext(ctx);vm.runInContext(code,ctx);
 ctx._handleNotifDeepLink();await new Promise(r=>setImmediate(r));
 assert.equal(loaded,1);assert.equal(replyScroll,1);assert.equal(rbox.classList.open,true);
 assert.equal(target.classList['fc-reply-highlight'],true);
 assert.equal(ctx._lastDeepLinkHash,'#post-p1-reply-42');
 assert.equal(ctx._openFeedNotification('/#post-p1-reply-42','reply'),true);
 await new Promise(r=>setImmediate(r));assert.equal(replyScroll,2,'clicking the same toast target opens it again');
 assert.equal(ctx._openFeedNotification('https://evil.example/#post-p1','reply'),false);
 ctx.location.hash='#post-p1';ctx._lastDeepLinkHash=null;ctx.sessionStorage.value='reply';
 ctx._handleNotifDeepLink();await new Promise(r=>setImmediate(r));assert.ok(rbox.classList.open,'legacy notification opens the thread');
 assert.equal(postScroll,3);
 console.log('PASS exact reply awaits loaded thread, opens/highlights target, repeat toast navigation, safe origin, legacy notification');
})().catch(e=>{console.error(e);process.exitCode=1});
