(function(){
'use strict';
if(window.OrcPageLifecycle)return;

var _setInterval=window.setInterval.bind(window);
var _clearInterval=window.clearInterval.bind(window);
var _fetch=window.fetch.bind(window);
var _MutationObserver=window.MutationObserver;
var _ResizeObserver=window.ResizeObserver;
var _IntersectionObserver=window.IntersectionObserver;

var intervals=new Set();
var observers=new Set();
var pendingReads=new Set();
var suspended=false;

function emit(name,detail){
  try{document.dispatchEvent(new CustomEvent(name,{detail:detail||{}}));}catch(_){}
}

function startInterval(rec){
  if(rec.stopped||suspended||rec.id!==null)return;
  rec.id=_setInterval.apply(window,[rec.fn,rec.delay].concat(rec.args));
}

function managedSetInterval(fn,delay){
  var args=Array.prototype.slice.call(arguments,2);
  var rec={__oaManagedInterval:true,fn:fn,delay:Number(delay)||0,args:args,id:null,stopped:false};
  rec.valueOf=function(){return rec.id==null?0:rec.id;};
  intervals.add(rec);
  startInterval(rec);
  return rec;
}

function managedClearInterval(handle){
  if(handle&&handle.__oaManagedInterval){
    handle.stopped=true;
    if(handle.id!==null){_clearInterval(handle.id);handle.id=null;}
    intervals.delete(handle);
    return;
  }
  _clearInterval(handle);
}

function wrapObserver(Ctor,callback,ctorOptions,kind){
  if(!Ctor)return null;
  var nativeObserver=(kind==='intersection')?new Ctor(callback,ctorOptions):new Ctor(callback);
  var nativeObserve=nativeObserver.observe.bind(nativeObserver);
  var nativeDisconnect=nativeObserver.disconnect.bind(nativeObserver);
  var watches=[];
  var rec={observer:nativeObserver,watches:watches,observe:nativeObserve,disconnect:nativeDisconnect,kind:kind,manual:false};

  nativeObserver.observe=function(target,options){
    if(!target)return;
    var found=false;
    for(var i=0;i<watches.length;i++){
      if(watches[i].target===target){watches[i].options=options;found=true;break;}
    }
    if(!found)watches.push({target:target,options:options});
    rec.manual=false;
    observers.add(rec);
    if(!suspended){
      if(kind==='mutation'||kind==='resize')nativeObserve(target,options);
      else nativeObserve(target);
    }
  };

  nativeObserver.disconnect=function(){
    rec.manual=true;
    watches.length=0;
    observers.delete(rec);
    nativeDisconnect();
  };

  observers.add(rec);
  return nativeObserver;
}

function managedMutationObserver(callback){
  return wrapObserver(_MutationObserver,callback,null,'mutation');
}

function managedResizeObserver(callback){
  return wrapObserver(_ResizeObserver,callback,null,'resize');
}

function managedIntersectionObserver(callback,options){
  return wrapObserver(_IntersectionObserver,callback,options,'intersection');
}

function requestMethod(input,init){
  return String((init&&init.method)||(input&&input.method)||'GET').toUpperCase();
}

function requestSignal(input,init){
  if(init&&init.signal)return init.signal;
  try{if(typeof Request!=='undefined'&&input instanceof Request)return input.signal||null;}catch(_){}
  return null;
}

function managedFetch(input,init){
  var method=requestMethod(input,init);
  if(method!=='GET'&&method!=='HEAD')return _fetch(input,init);

  var ctl=new AbortController();
  var upstream=requestSignal(input,init);
  var onAbort=null;
  if(upstream){
    if(upstream.aborted)ctl.abort();
    else{
      onAbort=function(){try{ctl.abort();}catch(_){}};
      upstream.addEventListener('abort',onAbort,{once:true});
    }
  }

  pendingReads.add(ctl);
  var opts=Object.assign({},init||{},{signal:ctl.signal});
  return _fetch(input,opts).finally(function(){
    pendingReads.delete(ctl);
    if(upstream&&onAbort)try{upstream.removeEventListener('abort',onAbort);}catch(_){}
  });
}

function suspend(reason,abortReads){
  if(!suspended){
    suspended=true;
    intervals.forEach(function(rec){
      if(rec.id!==null){_clearInterval(rec.id);rec.id=null;}
    });
    observers.forEach(function(rec){
      try{rec.disconnect();}catch(_){}
    });
  }
  if(abortReads){
    pendingReads.forEach(function(ctl){try{ctl.abort();}catch(_){}});
    pendingReads.clear();
  }
  emit('orca:lifecycle-suspend',{reason:reason||'pagehide'});
}

function resume(reason){
  if(!suspended)return;
  suspended=false;
  intervals.forEach(startInterval);
  observers.forEach(function(rec){
    if(rec.manual)return;
    rec.watches.forEach(function(w){
      try{
        if(rec.kind==='mutation'||rec.kind==='resize')rec.observe(w.target,w.options);
        else rec.observe(w.target);
      }catch(_){}
    });
  });
  emit('orca:lifecycle-resume',{reason:reason||'pageshow'});
}

function trackConnection(connection,closeMethod){
  if(!connection)return connection;
  var method=closeMethod||'close';
  var done=false;
  function close(){
    if(done)return;done=true;
    try{if(typeof connection[method]==='function')connection[method]();}catch(_){}
  }
  window.addEventListener('pagehide',close,{once:true});
  return connection;
}

window.OrcPageLifecycle={
  setInterval:managedSetInterval,
  clearInterval:managedClearInterval,
  mutationObserver:managedMutationObserver,
  resizeObserver:managedResizeObserver,
  intersectionObserver:managedIntersectionObserver,
  fetch:managedFetch,
  trackConnection:trackConnection,
  suspend:suspend,
  resume:resume,
  isSuspended:function(){return suspended;},
  stats:function(){return{intervals:intervals.size,observers:observers.size,pendingReads:pendingReads.size,suspended:suspended};}
};

window.fetch=managedFetch;

window.addEventListener('pagehide',function(){suspend('pagehide',true);},true);
window.addEventListener('pageshow',function(e){
  if(e.persisted||suspended)resume(e.persisted?'bfcache':'pageshow');
},true);
document.addEventListener('visibilitychange',function(){
  if(document.hidden)suspend('hidden',false);
  else resume('visible');
},true);
})();
