(function(){
'use strict';
if(window.OrcPageLifecycle)return;

var _setInterval=window.setInterval.bind(window);
var _clearInterval=window.clearInterval.bind(window);
var _setTimeout=window.setTimeout.bind(window);
var _clearTimeout=window.clearTimeout.bind(window);
var _requestAnimationFrame=window.requestAnimationFrame?window.requestAnimationFrame.bind(window):function(fn){return _setTimeout(fn,16);};
var _cancelAnimationFrame=window.cancelAnimationFrame?window.cancelAnimationFrame.bind(window):_clearTimeout;
var _fetch=window.fetch.bind(window);
var _MutationObserver=window.MutationObserver;
var _ResizeObserver=window.ResizeObserver;
var _IntersectionObserver=window.IntersectionObserver;

var intervals=new Set();
var observers=new Set();
var pendingReads=new Set();
var scopes=new Set();
var namedScopes=new Map();
var scopeRootObserver=null;
var suspended=false;
var lastPath=location.pathname;

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
  var rec={observer:nativeObserver,watches:watches,observe:nativeObserve,disconnect:nativeDisconnect,kind:kind,manual:false,pause:null};

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

  rec.pause=function(){
    try{nativeDisconnect();}catch(_){}
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

function fetchWithRegistry(registry,input,init){
  var method=requestMethod(input,init);
  // A route unmount may abort stale data reads. Never auto-abort mutations:
  // a submitted buy/sell/tip/setting change must not become ambiguous merely
  // because the user navigated away while the server was accepting it.
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

  registry.add(ctl);
  var opts=Object.assign({},init||{},{signal:ctl.signal});
  return _fetch(input,opts).finally(function(){
    registry.delete(ctl);
    if(upstream&&onAbort)try{upstream.removeEventListener('abort',onAbort);}catch(_){}
  });
}

function managedFetch(input,init){
  return fetchWithRegistry(pendingReads,input,init);
}

function closeConnection(connection,closeMethod,reason){
  if(!connection)return;
  var method=closeMethod||'close';
  try{
    if(typeof connection[method]!=='function')return;
    if(method==='close'&&typeof WebSocket!=='undefined'&&connection instanceof WebSocket){
      if(connection.readyState===WebSocket.OPEN||connection.readyState===WebSocket.CONNECTING){
        connection.close(1000,String(reason||'route unmount').slice(0,120));
      }
      return;
    }
    connection[method]();
  }catch(_){}
}

function stopRootObserverIfIdle(){
  if(scopes.size||!scopeRootObserver)return;
  try{scopeRootObserver.disconnect();}catch(_){}
  scopeRootObserver=null;
}

function ensureRootObserver(){
  if(scopeRootObserver||!_MutationObserver||!document.documentElement)return;
  scopeRootObserver=new _MutationObserver(function(){
    Array.from(scopes).forEach(function(scope){
      if(scope.root&&!scope.root.isConnected)scope.cleanup('dom-unmount');
    });
  });
  scopeRootObserver.observe(document.documentElement,{childList:true,subtree:true});
}

function createScope(name,root){
  var alive=true;
  var rootSelector=typeof root==='string'?root:null;
  var initialRoot=rootSelector?document.querySelector(rootSelector):(root||null);
  var scopeIntervals=new Set();
  var timeouts=new Set();
  var rafs=new Set();
  var listeners=[];
  var scopeObservers=new Set();
  var scopeReads=new Set();
  var connections=new Set();
  var cleanups=[];
  var scope={
    name:String(name||'route'),
    root:initialRoot,
    isActive:function(){return alive;},
    fetch:function(input,init){
      if(!alive){
        var err=new Error('Route scope has unmounted');
        err.name='AbortError';
        return Promise.reject(err);
      }
      return fetchWithRegistry(scopeReads,input,init);
    },
    setInterval:function(fn,delay){
      if(!alive)return null;
      var args=Array.prototype.slice.call(arguments,2);
      var h=managedSetInterval.apply(window,[fn,delay].concat(args));
      scopeIntervals.add(h);
      return h;
    },
    clearInterval:function(h){
      scopeIntervals.delete(h);
      managedClearInterval(h);
    },
    setTimeout:function(fn,delay){
      if(!alive)return null;
      var args=Array.prototype.slice.call(arguments,2);
      var h=_setTimeout(function(){
        timeouts.delete(h);
        if(!alive)return;
        if(typeof fn==='function')fn.apply(window,args);
      },delay);
      timeouts.add(h);
      return h;
    },
    clearTimeout:function(h){
      timeouts.delete(h);
      _clearTimeout(h);
    },
    requestAnimationFrame:function(fn){
      if(!alive)return null;
      var h=_requestAnimationFrame(function(ts){
        rafs.delete(h);
        if(alive&&typeof fn==='function')fn(ts);
      });
      rafs.add(h);
      return h;
    },
    cancelAnimationFrame:function(h){
      rafs.delete(h);
      _cancelAnimationFrame(h);
    },
    addEventListener:function(target,type,listener,options){
      if(!alive||!target||typeof target.addEventListener!=='function')return listener;
      target.addEventListener(type,listener,options);
      listeners.push({target:target,type:type,listener:listener,options:options});
      return listener;
    },
    mutationObserver:function(callback){
      var ob=managedMutationObserver(callback);
      if(ob)scopeObservers.add(ob);
      return ob;
    },
    resizeObserver:function(callback){
      var ob=managedResizeObserver(callback);
      if(ob)scopeObservers.add(ob);
      return ob;
    },
    intersectionObserver:function(callback,options){
      var ob=managedIntersectionObserver(callback,options);
      if(ob)scopeObservers.add(ob);
      return ob;
    },
    trackConnection:function(connection,closeMethod){
      if(connection)connections.add({connection:connection,closeMethod:closeMethod||'close'});
      return connection;
    },
    onCleanup:function(fn){
      if(typeof fn==='function')cleanups.push(fn);
      return fn;
    },
    abortReads:function(){
      scopeReads.forEach(function(ctl){try{ctl.abort();}catch(_){}});
      scopeReads.clear();
    },
    bind:function(el){
      scope.root=el||null;
      if(scope.root)ensureRootObserver();
      return scope;
    },
    cleanup:function(reason){
      if(!alive)return;
      alive=false;

      scopeReads.forEach(function(ctl){try{ctl.abort();}catch(_){}});
      scopeReads.clear();

      scopeIntervals.forEach(function(h){managedClearInterval(h);});
      scopeIntervals.clear();

      timeouts.forEach(function(h){_clearTimeout(h);});
      timeouts.clear();

      rafs.forEach(function(h){_cancelAnimationFrame(h);});
      rafs.clear();

      listeners.forEach(function(rec){
        try{rec.target.removeEventListener(rec.type,rec.listener,rec.options);}catch(_){}
      });
      listeners.length=0;

      scopeObservers.forEach(function(ob){try{ob.disconnect();}catch(_){}});
      scopeObservers.clear();

      connections.forEach(function(rec){closeConnection(rec.connection,rec.closeMethod,reason);});
      connections.clear();

      cleanups.splice(0).forEach(function(fn){try{fn(reason||'unmount');}catch(_){}});

      scopes.delete(scope);
      if(namedScopes.get(scope.name)===scope)namedScopes.delete(scope.name);
      stopRootObserverIfIdle();
      emit('orca:scope-cleanup',{name:scope.name,reason:reason||'unmount'});
    },
    stats:function(){
      return{
        active:alive,
        reads:scopeReads.size,
        intervals:scopeIntervals.size,
        timeouts:timeouts.size,
        rafs:rafs.size,
        listeners:listeners.length,
        observers:scopeObservers.size,
        connections:connections.size
      };
    }
  };
  scopes.add(scope);
  if(scope.root)ensureRootObserver();
  else if(rootSelector&&document.readyState==='loading'){
    scope.addEventListener(document,'DOMContentLoaded',function(){
      if(alive)scope.bind(document.querySelector(rootSelector));
    },{once:true});
  }
  return scope;
}

function routeScope(name,root){
  name=String(name||'route');
  var existing=namedScopes.get(name);
  if(existing&&existing.isActive()){
    if(root&&!existing.root){
      var el=typeof root==='string'?document.querySelector(root):root;
      if(el)existing.bind(el);
    }
    return existing;
  }
  var scope=createScope(name,root);
  namedScopes.set(name,scope);
  return scope;
}

function cleanupRouteScopes(reason){
  var active=Array.from(scopes);
  active.forEach(function(scope){scope.cleanup(reason||'route-unmount');});
  if(active.length)emit('orca:route-unmount',{reason:reason||'route-unmount',count:active.length});
}

function targetPath(url){
  if(url==null)return location.pathname;
  try{return new URL(String(url),location.href).pathname;}catch(_){return location.pathname;}
}

function installHistoryCleanup(){
  if(!window.history)return;
  var rawPush=history.pushState&&history.pushState.bind(history);
  var rawReplace=history.replaceState&&history.replaceState.bind(history);

  if(rawPush){
    history.pushState=function(state,title,url){
      var next=targetPath(url);
      if(next!==location.pathname)cleanupRouteScopes('history-push');
      var result=rawPush(state,title,url);
      lastPath=location.pathname;
      return result;
    };
  }

  if(rawReplace){
    history.replaceState=function(state,title,url){
      var next=targetPath(url);
      if(next!==location.pathname)cleanupRouteScopes('history-replace');
      var result=rawReplace(state,title,url);
      lastPath=location.pathname;
      return result;
    };
  }

  window.addEventListener('popstate',function(){
    var next=location.pathname;
    if(next!==lastPath)cleanupRouteScopes('popstate');
    lastPath=next;
  },true);
}

function suspend(reason,abortReads){
  if(!suspended){
    suspended=true;
    intervals.forEach(function(rec){
      if(rec.id!==null){_clearInterval(rec.id);rec.id=null;}
    });
    observers.forEach(function(rec){
      try{if(rec.pause)rec.pause();}catch(_){}
    });
  }
  if(abortReads){
    pendingReads.forEach(function(ctl){try{ctl.abort();}catch(_){}});
    pendingReads.clear();
    scopes.forEach(function(scope){
      // Scope cleanup is deliberately NOT called here: a BFCache page is
      // frozen, not unmounted. Abort only stale reads; keep the mounted scope
      // so pageshow can resume its intervals/observers.
      if(scope&&scope.abortReads)scope.abortReads();
    });
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
  var done=false;
  function close(){
    if(done)return;done=true;
    closeConnection(connection,closeMethod,'pagehide');
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
  createScope:createScope,
  routeScope:routeScope,
  cleanupRouteScopes:cleanupRouteScopes,
  suspend:suspend,
  resume:resume,
  isSuspended:function(){return suspended;},
  stats:function(){return{intervals:intervals.size,observers:observers.size,pendingReads:pendingReads.size,scopes:scopes.size,suspended:suspended};}
};

window.fetch=managedFetch;
installHistoryCleanup();

window.addEventListener('pagehide',function(){suspend('pagehide',true);},true);
window.addEventListener('pageshow',function(e){
  if(e.persisted||suspended)resume(e.persisted?'bfcache':'pageshow');
},true);
document.addEventListener('visibilitychange',function(){
  if(document.hidden)suspend('hidden',false);
  else resume('visible');
},true);
})();
