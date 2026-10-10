const fs=require('fs'),vm=require('vm'),assert=require('assert');
let tick,resolve,calls=0,listeners={};
const context={document:{hidden:false,body:{}},window:{OrcAgentGetPortfolioSnapshot(){calls++;return new Promise(r=>resolve=r);}},OrcPageLifecycle:{routeScope(){return {setInterval(f,ms){assert.equal(ms,5000);tick=f;},addEventListener(t,n,f){listeners[n]=f;}};}}};
vm.runInNewContext(fs.readFileSync('static/portfolio-live-refresh.js','utf8'),context);
(async()=>{tick();tick();assert.equal(calls,1);resolve({});await new Promise(r=>setImmediate(r));context.document.hidden=true;tick();assert.equal(calls,1);context.document.hidden=false;listeners.visibilitychange();assert.equal(calls,2);console.log('PASS: coalesced refresh, hidden pause, visible resume');})();
