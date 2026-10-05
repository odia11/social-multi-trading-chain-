const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const src=fs.readFileSync('static/dashboard.js','utf8');
const mint='98kfF7rmsg1QDUEoCqNE7g7M1FdrTt92TEp2CLzypump';
const prompt={id:137,parent_reply_id:136,verified:true,username:'Orcagent',message:'Do you mean $PAID? Several Solana tokens match.'};
const selected={id:138,parent_reply_id:137,message:'@orcagent $PAID ('+mint+') what is the price?'};
let rows=[];
const ctx={console,Map,Set,String,Array,Promise,_renderReplyRow(r,p,d){rows.push([r.id,d]);return r.id+','}};
vm.createContext(ctx);
vm.runInContext(src.slice(src.indexOf('function _feedRenderReplyTree('),src.indexOf('function _feedLoadReplies(')),ctx);
function render(replies){rows=[];ctx._feedRenderReplyTree(replies,'554');return rows.map(r=>r[0])}
assert.deepEqual(render([{id:136},prompt]),[136,137],'unselected prompt remains');
assert.deepEqual(render([{id:136},prompt,selected,{id:139,parent_reply_id:138}]),[136,138,139]);
assert.equal(rows[1][1],1,'selection takes the hidden prompt depth');
assert.deepEqual(render([prompt,selected]),[138],'root chooser also resolves after reload');
assert.deepEqual(render([prompt,{...selected,message:'@orcagent $OTHER ('+mint+') what is the price?'}]),[137,138]);
assert.deepEqual(render([prompt,{...selected,message:'@orcagent $PAID what is the price?'}]),[137,138],'ambiguous question is not a selection');
assert.deepEqual(render([{...prompt,verified:false},selected]),[137,138],'unverified account cannot create a temporary agent prompt');

async function submission(ok,networkError=false){
 let removed=0,inserted=0,reloaded=0,alerts=0;
 const parent={dataset:{tokenChoice:'PAID',parentId:'136'},insertAdjacentHTML(){inserted++},remove(){removed++}};
 const c={Promise,JSON,_myProfileData:null,_RC_SEND_ICON_SVG:'send',_renderReplyRow:()=>'',openAlertModal(){alerts++},_feedLoadReplies(){reloaded++},
  document:{querySelector:()=>parent,getElementById:()=>null},
  fetch:async()=>{if(networkError)throw Error('offline');return {json:async()=>({ok,id:138,message:selected.message})}}};
 vm.createContext(c);
 vm.runInContext(src.slice(src.indexOf('function _feedSubmitNestedReply('),src.indexOf('function _feedRenderReplyTree(')),c);
 const input={value:selected.message,disabled:false};
 const saved=await c._feedSubmitNestedReply(input,'554',137);
 assert.equal(saved,ok&&!networkError);
 assert.equal(removed,ok&&!networkError?1:0);
 assert.equal(inserted,removed);assert.equal(reloaded,removed);
 assert.equal(alerts,removed?0:1);assert.equal(input.disabled,false);
 input.disabled=true;assert.equal(await c._feedSubmitNestedReply(input,'554',137),false);
}

async function choiceTest(){
 let posts=0,request,handler;
 const buttons=[];
 const host={isConnected:true,replaceChildren(){buttons.length=0},appendChild(b){buttons.push(b)},querySelectorAll(){return buttons}};
 const c={Set,String,Array,encodeURIComponent,safeMint:()=>true,safeImageUrl:()=>'',
 document:{createElement(type){return {style:{},appendChild(){},addEventListener(event,fn){handler=fn}}}},
 fetch:async()=>({ok:true,json:async()=>({pairs:[{chainId:'solana',baseToken:{symbol:'PAID',address:mint,name:'Paid'}}]})}),
 _feedSubmitNestedReply:async(input,post,parent)=>{posts++;request=[input.value,post,parent];await Promise.resolve();return false}};
 vm.createContext(c);
 vm.runInContext(src.slice(src.indexOf('async function _assistantTokenChoices('),src.indexOf('function _feedToggleNestedReply(')),c);
 await c._assistantTokenChoices({parentElement:host},'PAID',137,'554');
 const first=handler({stopPropagation(){}});
 await handler({stopPropagation(){}});
 await first;
 assert.equal(posts,1,'double click must not duplicate selection');
 assert.deepEqual(request,[selected.message,'554',137],'choice immediately submits exact token');
 assert.equal(buttons[0].disabled,false,'failed submission can be retried');
}
(async()=>{await submission(true);await submission(false);await submission(false,true);await choiceTest();console.log('PASS completed chooser reload, descendants, exact identity, automatic submission, double click and failure retry')})().catch(e=>{console.error(e);process.exitCode=1});
