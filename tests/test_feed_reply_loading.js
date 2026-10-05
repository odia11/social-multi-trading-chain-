const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const src=fs.readFileSync('static/dashboard.js','utf8');
let response,requests=0,renderError=false,currentList;
const box={dataset:{},classList:{opened:false,toggle(){return this.opened=!this.opened}}};
const list={innerHTML:'',querySelector(s){return s==='.fc-reply-item'&&this.innerHTML.includes('reply-row')?{}:null},querySelectorAll(){return this.innerHTML.includes('reply-row')?[{}]:[]},setAttribute(){},removeAttribute(){},insertAdjacentHTML(_,s){this.innerHTML=s+this.innerHTML}};
currentList=list;
const ctx={Array,Promise,Date,String,encodeURIComponent,esc:String,setTimeout(){},
 document:{getElementById(id){return id==='rlist-p554'?currentList:id==='rbox-p554'?box:null}},
 fetch(){requests++;return response()},_feedRenderReplyTree(){if(renderError)throw Error('render');return 'reply-row'}};
vm.createContext(ctx);
vm.runInContext(src.slice(src.indexOf('function _feedLoadReplies('),src.indexOf('function _feedLikeReply(')),ctx);
vm.runInContext(src.slice(src.indexOf('function _feedToggleReply('),src.indexOf('/* ── Canonical post deep-links:')),ctx);
function ok(replies=[{id:134}]){return Promise.resolve({ok:true,json:async()=>({ok:true,replies})})}
(async()=>{
 response=()=>Promise.reject(Error('network'));
 ctx._feedToggleReply(null,'p554');await list._replyLoad;
 assert.ok(list.innerHTML.includes('Try again'),'failed load must be visible');
 assert.equal(box.dataset.repliesLoaded,undefined,'failure must not poison loaded state');
 ctx._feedToggleReply(null,'p554');response=()=>ok();ctx._feedToggleReply(null,'p554');await list._replyLoad;
 assert.ok(list.innerHTML.includes('reply-row'));assert.equal(box.dataset.repliesLoaded,'1');assert.equal(requests,2,'reopen retries');
 ctx._feedToggleReply(null,'p554');ctx._feedToggleReply(null,'p554');await list._replyLoad;
 assert.equal(requests,3,'reopen successful thread refreshes it');
 response=()=>Promise.resolve({ok:false,json:async()=>({})});
 assert.equal(await ctx._feedLoadReplies('p554'),false);
 assert.ok(list.innerHTML.includes('reply-row')&&list.innerHTML.includes('Try again'),'refresh error preserves existing replies');
 response=()=>ok();renderError=true;
 assert.equal(await ctx._feedLoadReplies('p554'),false);renderError=false;
 assert.equal(box.dataset.repliesLoaded,undefined);
 list.innerHTML='';let finish;response=()=>new Promise(r=>finish=r);
 const first=ctx._feedLoadReplies('p554'),second=ctx._feedLoadReplies('p554');
 assert.equal(first,second,'duplicate loads share the pending request');
 assert.ok(list.innerHTML.includes('Loading replies'));
 assert.equal(box.dataset.repliesLoaded,undefined,'pending request is not loaded');
 finish(await ok());assert.equal(await first,true);
 response=()=>ok([]);assert.equal(await ctx._feedLoadReplies('p554'),true);assert.ok(list.innerHTML.includes('No replies yet'));
 response=()=>Promise.resolve({ok:true,json:async()=>({ok:false})});assert.equal(await ctx._feedLoadReplies('p554'),false);
 response=()=>new Promise(r=>finish=r);const stale=ctx._feedLoadReplies('p554');
 currentList={innerHTML:'new card'};finish(await ok());assert.equal(await stale,false);assert.equal(currentList.innerHTML,'new card');
 console.log('PASS desktop thread retry, loading state, refresh, HTTP/API/render errors, preserved replies, request deduplication and replaced cards');
})().catch(e=>{console.error(e);process.exitCode=1});
