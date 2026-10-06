const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

class Emitter {
  constructor(){ this.map=new Map(); }
  addEventListener(type,fn){
    if(!this.map.has(type)) this.map.set(type,new Set());
    this.map.get(type).add(fn);
  }
  removeEventListener(type,fn){
    const set=this.map.get(type); if(set)set.delete(fn);
  }
  dispatchEvent(event){
    const set=this.map.get(event.type);
    if(set) Array.from(set).forEach(fn=>fn.call(this,event));
    return true;
  }
}
class FakeObserver {
  constructor(cb){ this.cb=cb; this.targets=[]; this.disconnected=false; }
  observe(target,options){ this.targets.push({target,options}); this.disconnected=false; }
  disconnect(){ this.disconnected=true; this.targets=[]; }
}
class FakeCustomEvent {
  constructor(type,init){ this.type=type; this.detail=init&&init.detail; }
}

const nativeSetInterval=setInterval;
const nativeClearInterval=clearInterval;
const nativeSetTimeout=setTimeout;
const nativeClearTimeout=clearTimeout;
const clearedIntervals=new Set();
const clearedTimeouts=new Set();
const cancelledRafs=new Set();
global.clearInterval=function(handle){ clearedIntervals.add(handle); return nativeClearInterval(handle); };
global.clearTimeout=function(handle){ clearedTimeouts.add(handle); return nativeClearTimeout(handle); };
const windowEvents=new Emitter();
const documentEvents=new Emitter();
const root={isConnected:true};

global.window=global;
global.addEventListener=windowEvents.addEventListener.bind(windowEvents);
global.removeEventListener=windowEvents.removeEventListener.bind(windowEvents);
global.dispatchEvent=windowEvents.dispatchEvent.bind(windowEvents);
global.document={
  readyState:'complete',
  documentElement:{},
  querySelector(sel){ return sel==='#lazy-root'?root:null; },
  addEventListener:documentEvents.addEventListener.bind(documentEvents),
  removeEventListener:documentEvents.removeEventListener.bind(documentEvents),
  dispatchEvent:documentEvents.dispatchEvent.bind(documentEvents)
};
global.CustomEvent=FakeCustomEvent;
global.MutationObserver=FakeObserver;
global.ResizeObserver=FakeObserver;
global.IntersectionObserver=FakeObserver;
global.location={pathname:'/live-market',href:'https://orcagent.fun/live-market'};
global.history={
  pushState(_state,_title,url){
    const u=new URL(String(url),location.href);
    location.pathname=u.pathname; location.href=u.href;
  },
  replaceState(_state,_title,url){
    const u=new URL(String(url),location.href);
    location.pathname=u.pathname; location.href=u.href;
  }
};
global.requestAnimationFrame=fn=>nativeSetTimeout(()=>fn(Date.now()),30000);
global.cancelAnimationFrame=id=>{ cancelledRafs.add(id); return nativeClearTimeout(id); };

let abortedReads=0;
global.fetch=function(_input,init){
  init=init||{};
  return new Promise((_resolve,reject)=>{
    const signal=init.signal;
    if(!signal)return;
    const aborted=()=>{
      abortedReads++;
      const err=new Error('aborted'); err.name='AbortError'; reject(err);
    };
    if(signal.aborted)aborted();
    else signal.addEventListener('abort',aborted,{once:true});
  });
};

vm.runInThisContext(fs.readFileSync('static/page-lifecycle.js','utf8'),{filename:'page-lifecycle.js'});

(async()=>{
  const scope=OrcPageLifecycle.routeScope('lazy-live-market','#lazy-root');
  assert.equal(OrcPageLifecycle.routeScope('lazy-live-market','#lazy-root'),scope,
    'named route scripts must share one scope');

  let ticks=0, timeoutFired=false, rafFired=false, events=0, customCleanups=0;
  const intervalHandle=scope.setInterval(()=>{ticks++;},5);
  const nativeIntervalHandle=intervalHandle.id;
  const timeoutHandle=scope.setTimeout(()=>{timeoutFired=true;},30000);
  const rafHandle=scope.requestAnimationFrame(()=>{rafFired=true;});

  const target=new Emitter();
  scope.addEventListener(target,'ping',()=>{events++;});
  target.dispatchEvent({type:'ping'});
  assert.equal(events,1,'listener works while route is mounted');

  const observer=scope.mutationObserver(()=>{});
  observer.observe(root,{attributes:true});

  const socket={closed:0,close(){this.closed++;}};
  scope.trackConnection(socket);

  const pendingRead=scope.fetch('/api/live-data').catch(err=>err);
  scope.onCleanup(()=>{customCleanups++;});

  await new Promise(r=>nativeSetTimeout(r,16));
  assert(ticks>0,'interval runs while route is mounted');

  history.pushState({},'', '/wallet');

  const after=scope.stats();
  assert.equal(after.active,false,'scope becomes inactive on lazy route navigation');
  assert.equal(after.reads,0,'all scoped GET/HEAD requests are removed');
  assert.equal(after.intervals,0,'all intervals are cleared');
  assert.equal(clearedIntervals.has(nativeIntervalHandle),true,'native interval is explicitly cancelled');
  assert.equal(after.timeouts,0,'all timeouts are cleared');
  assert.equal(clearedTimeouts.has(timeoutHandle),true,'pending native timeout is explicitly cancelled');
  assert.equal(after.rafs,0,'all animation frames are cancelled');
  assert.equal(cancelledRafs.has(rafHandle),true,'pending native animation frame is explicitly cancelled');
  assert.equal(after.listeners,0,'all event listeners are removed');
  assert.equal(after.observers,0,'all observers are disconnected');
  assert.equal(after.connections,0,'all tracked connections are closed');
  assert.equal(socket.closed,1,'tracked connection closes exactly once');
  assert.equal(customCleanups,1,'custom cleanup runs exactly once');
  assert.equal(observer.disconnected,true,'observer native disconnect ran');

  const result=await pendingRead;
  assert.equal(result&&result.name,'AbortError','in-flight read fetch aborts on unmount');
  assert.equal(abortedReads,1,'read fetch receives one abort');

  const frozenTicks=ticks;
  target.dispatchEvent({type:'ping'});
  assert.equal(ticks,frozenTicks,'interval stays stopped after unmount');
  assert.equal(events,1,'removed listener never fires after unmount');
  assert.equal(timeoutFired,false,'cancelled timeout did not run before cleanup completed');
  assert.equal(rafFired,false,'cancelled animation frame did not run before cleanup completed');

  const remount=OrcPageLifecycle.routeScope('lazy-live-market','#lazy-root');
  assert.notEqual(remount,scope,'a later lazy remount receives a fresh scope');
  remount.cleanup('test-end');

  nativeClearInterval();
  console.log('PASS lazy route unmount closes fetches, timers, listeners, observers and connections');
})().catch(err=>{ console.error(err); process.exit(1); });
