// Exercise the actual polling function with an initially empty personal inbox.
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const src=fs.readFileSync('static/in-app-notifications.js','utf8');
const poll=src.slice(src.indexOf('function poll(initial){'),src.indexOf('\nfunction schedule(){'));
function harness(responses,lastId=0){
 const shown=[],requests=[];
 const context={inFlight:false,document:{hidden:false},primed:lastId>0,lastId,MAX_BATCH:8,POLL_MAX_MS:15000,POLL_MS:6000,pollDelay:6000,
  fetch(url){requests.push(url);const response=responses.shift();return Promise.resolve({ok:!!response,status:response?200:503,json(){return Promise.resolve(response);}})},
  writeLastId(){},enqueue(items){shown.push(...items)},encodeURIComponent,Promise,Math};
 vm.createContext(context);vm.runInContext(poll,context);
 return {context,shown,requests,async poll(){context.poll(true);await new Promise(r=>setImmediate(r));}};
}
(async()=>{
 const deposit={id:1,type:'deposit',content:'You received 1 SOL'};
 const h=harness([{ok:true,notifications:[]},{ok:true,notifications:[deposit]},{ok:true,notifications:[]}]);
 await h.poll();assert.equal(h.context.primed,true);assert.equal(h.shown.length,0);
 await h.poll();assert.equal(h.shown.length,1);assert.equal(h.shown[0].type,'deposit');assert.equal(h.context.lastId,1);
 await h.poll();assert.equal(h.shown.length,1);assert.ok(h.requests[2].includes('after_id=1'));
 const existing=harness([{ok:true,notifications:[{id:10,type:'like'}]},{ok:true,notifications:[{id:11,type:'deposit'}]}]);
 await existing.poll();assert.equal(existing.shown.length,0);
 await existing.poll();assert.equal(existing.shown.length,1);
 const failed=harness([null,{ok:true,notifications:[]}]);
 await failed.poll();assert.equal(failed.context.primed,false);await failed.poll();assert.equal(failed.context.primed,true);
 console.log('PASS empty inbox first deposit, no history replay, incremental deduplication and failed-request retry');
})().catch(e=>{console.error(e);process.exit(1)});
