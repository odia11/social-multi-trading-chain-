// OrcAgent service worker — public app-shell cache + Web Push.
// SECURITY INVARIANT: only /static/ GETs enter Cache Storage. Authenticated
// navigation HTML may be warmed only in short-lived per-client RAM; APIs,
// balances and wallet data are never persisted by the service worker.
var OA_BUILD_VERSION=(new URL(self.location.href)).searchParams.get('v')||'dev';
OA_BUILD_VERSION=String(OA_BUILD_VERSION).replace(/[^A-Za-z0-9_.-]/g,'').slice(0,64)||'dev';
var OA_STATIC_CACHE = 'orcagent-static-'+OA_BUILD_VERSION;
var OA_DEPLOY_RETRY_DELAYS = [250,500,1000,1500,2000,2500,3000,3500,4000];
// X-style navigation warmup: authenticated HTML is NEVER written to Cache
// Storage. A target document may live for a few seconds in this service
// worker's RAM, scoped to the browser client that requested it, so the real
// native navigation can reuse an already-started network request.
var OA_NAV_TTL_MS = 7000;
var OA_NAV_MAX_READY = 6;
var OA_NAV_SAFE_PREFIXES = [
  '/live-market','/wallet','/profile','/messages','/notifications','/groups',
  '/traders','/calls','/call','/leaderboard','/history',
  '/referrals','/settings','/auto-trading-bot','/bot','/token-launch',
  '/token-launches','/live-trades','/promote','/info'
];
var OA_NAV_READY = new Map();
var OA_NAV_INFLIGHT = new Map();
function oaWait(ms){ return new Promise(function(resolve){ setTimeout(resolve, ms); }); }
function oaNavWarmablePath(p){
  if(p==='/') return true;
  for(var i=0;i<OA_NAV_SAFE_PREFIXES.length;i++){
    var base=OA_NAV_SAFE_PREFIXES[i];
    if(p===base || p.indexOf(base+'/')===0) return true;
  }
  return false;
}
function oaNavHref(raw){
  var u;
  try{ u=new URL(raw,self.location.origin); }catch(_){ return ''; }
  if(u.origin!==self.location.origin) return '';
  var p=u.pathname||'/';
  if(p.indexOf('/api/')===0 || !oaNavWarmablePath(p)) return '';
  u.hash='';
  return u.href;
}
function oaNavKey(clientId,href){ return String(clientId||'')+'|'+href; }
function oaTrimNavWarm(now){
  now=now||Date.now();
  OA_NAV_READY.forEach(function(entry,key){
    if(!entry || now-entry.ts>OA_NAV_TTL_MS) OA_NAV_READY.delete(key);
  });
  OA_NAV_INFLIGHT.forEach(function(entry,key){
    if(!entry || now-entry.ts>OA_NAV_TTL_MS) OA_NAV_INFLIGHT.delete(key);
  });
  while(OA_NAV_READY.size>OA_NAV_MAX_READY){
    var first=OA_NAV_READY.keys().next();
    if(first.done) break;
    OA_NAV_READY.delete(first.value);
  }
}
function oaFetchThroughDeploy(req, attempt){
  return fetch(req.clone()).then(function(resp){
    if(attempt < OA_DEPLOY_RETRY_DELAYS.length &&
       (resp.status===502 || resp.status===503 || resp.status===504)){
      return oaWait(OA_DEPLOY_RETRY_DELAYS[attempt]).then(function(){
        return oaFetchThroughDeploy(req, attempt+1);
      });
    }
    return resp;
  }).catch(function(err){
    if(attempt < OA_DEPLOY_RETRY_DELAYS.length){
      return oaWait(OA_DEPLOY_RETRY_DELAYS[attempt]).then(function(){
        return oaFetchThroughDeploy(req, attempt+1);
      });
    }
    throw err;
  });
}
function oaStartNavPrefetch(clientId,rawUrl){
  var href=oaNavHref(rawUrl);
  if(!href) return Promise.resolve(null);
  oaTrimNavWarm();
  var key=oaNavKey(clientId,href), ready=OA_NAV_READY.get(key), pending=OA_NAV_INFLIGHT.get(key);
  if(ready && Date.now()-ready.ts<=OA_NAV_TTL_MS) return Promise.resolve(ready.response.clone());
  if(pending) return pending.promise;
  var req=new Request(href,{
    method:'GET',credentials:'include',cache:'no-store',redirect:'follow',
    headers:{'Accept':'text/html,application/xhtml+xml','X-OrcAgent-Nav-Warm':'1'}
  });
  var record={href:href,clientId:String(clientId||''),ts:Date.now(),promise:null};
  record.promise=oaFetchThroughDeploy(req,0).then(function(resp){
    if(!resp || !resp.ok || resp.redirected || (resp.url && oaNavHref(resp.url)!==href)) return null;
    var ctype=(resp.headers.get('content-type')||'').toLowerCase();
    if(ctype.indexOf('text/html')===-1) return null;
    OA_NAV_READY.set(key,{href:href,clientId:record.clientId,ts:Date.now(),response:resp.clone()});
    oaTrimNavWarm();
    return resp;
  }).catch(function(){ return null; }).finally(function(){ OA_NAV_INFLIGHT.delete(key); });
  OA_NAV_INFLIGHT.set(key,record);
  return record.promise;
}
function oaFindNavWarm(event,href){
  oaTrimNavWarm();
  var ids=[event.clientId||'',event.resultingClientId||''];
  for(var i=0;i<ids.length;i++){
    if(!ids[i]) continue;
    var key=oaNavKey(ids[i],href);
    if(OA_NAV_READY.has(key)) return {key:key,ready:OA_NAV_READY.get(key)};
    if(OA_NAV_INFLIGHT.has(key)) return {key:key,pending:OA_NAV_INFLIGHT.get(key)};
  }
  // Safari can omit clientId on a navigation FetchEvent. Browser cookies are
  // origin-wide, so a same-origin warm entry from the only signed-in session
  // is still safe to reuse. Keep this fallback short-lived and URL-exact.
  var found=null;
  OA_NAV_READY.forEach(function(entry,key){ if(!found && entry.href===href) found={key:key,ready:entry}; });
  if(found) return found;
  OA_NAV_INFLIGHT.forEach(function(entry,key){ if(!found && entry.href===href) found={key:key,pending:entry}; });
  return found;
}
function oaNavigationResponse(event,req,href){
  var warm=oaFindNavWarm(event,href);
  if(warm && warm.ready){
    OA_NAV_READY.delete(warm.key);
    return Promise.resolve(warm.ready.response.clone());
  }
  if(warm && warm.pending){
    return warm.pending.promise.then(function(resp){
      OA_NAV_READY.delete(warm.key);
      return resp ? resp.clone() : oaFetchThroughDeploy(req,0);
    }).catch(function(){ return oaFetchThroughDeploy(req,0); });
  }
  return oaFetchThroughDeploy(req,0);
}
function oaStaticBuild(path){
  return path+'?v='+encodeURIComponent(OA_BUILD_VERSION);
}
var OA_STATIC_BOOT = [
  oaStaticBuild('/static/page-lifecycle.js'),
  oaStaticBuild('/static/app-ux.css'),
  oaStaticBuild('/static/app-ux.js'),
  oaStaticBuild('/static/mobile-bottom-nav.css'),
  oaStaticBuild('/static/mobile-bottom-nav.js')
];
self.addEventListener('install', function(event) {
  event.waitUntil(
    caches.open(OA_STATIC_CACHE).then(function(cache){
      return Promise.all(OA_STATIC_BOOT.map(function(url){
        return cache.add(url).catch(function(){ return null; });
      }));
    }).then(function(){ return self.skipWaiting(); })
  );
});
self.addEventListener('activate', function(event) {
  event.waitUntil(
    caches.keys().then(function(keys){
      return Promise.all(keys.filter(function(k){
        return k.indexOf('orcagent-static-')===0 && k!==OA_STATIC_CACHE;
      }).map(function(k){ return caches.delete(k); }));
    }).then(function(){ return self.clients.claim(); })
  );
});
self.addEventListener('message', function(event){
  var data=event.data||{};
  if(data.type!=='oa-nav-prefetch' || typeof data.url!=='string') return;
  var clientId=(event.source&&event.source.id)||'';
  var source=event.source;
  var work=oaStartNavPrefetch(clientId,data.url).then(function(resp){
    if(resp&&source&&typeof source.postMessage==='function'){
      try{source.postMessage({type:'oa-nav-ready',url:data.url})}catch(_){}
    }
    return resp;
  });
  if(event.waitUntil) event.waitUntil(work);
});
self.addEventListener('fetch', function(event) {
  var req=event.request;
  if(req.method!=='GET') return;
  var url;
  try{ url=new URL(req.url); }catch(_){ return; }
  if(url.origin!==self.location.origin) return;

  // Native navigation stays authoritative. If pointer/touch intent already
  // started this exact document request, reuse that short-lived in-memory
  // response; otherwise fetch normally with the deploy-retry shield. No HTML
  // response from this branch is ever written to Cache Storage.
  if(req.mode==='navigate'){
    var navHref=oaNavHref(url.href);
    event.respondWith(navHref ? oaNavigationResponse(event,req,navHref) : oaFetchThroughDeploy(req,0));
    return;
  }

  if(url.pathname.indexOf('/static/')!==0) return;
  event.respondWith(
    caches.open(OA_STATIC_CACHE).then(function(cache){
      return cache.match(req).then(function(hit){
        var network=fetch(req).then(function(resp){
          if(resp && resp.ok) cache.put(req, resp.clone()).catch(function(){});
          return resp;
        });
        if(hit){
          event.waitUntil(network.catch(function(){}));
          return hit;
        }
        return network;
      });
    })
  );
});
self.addEventListener('push', function(event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) {}
  var title = data.title || 'OrcAgent';
  var body  = data.body  || '';
  var url   = data.url   || '/';
  event.waitUntil(
    // icon: the token's own logo when the sender supplied one, so a surge
    // alert is recognisable as THAT token at a glance. Falls back to the
    // OrcAgent mark for every other kind of notification, and for a token
    // with no logo.
    //
    // badge deliberately stays ours: it is the tiny monochrome glyph the
    // system stamps to say WHICH APP buzzed, and a token logo there would
    // be both unreadable at that size and a lie about the sender.
    // tag (optional): a newer alert with the same tag replaces the older one
    // instead of stacking, and the app can close it once the same thing is
    // on screen (e.g. the "Trending now" card on the home feed).
    self.registration.showNotification(title, Object.assign({
      body: body,
      icon: data.icon || '/favicon.svg?v=2',
      badge: '/favicon.svg?v=2',
      data: { url: url }
    }, data.tag ? { tag: String(data.tag).slice(0, 64), renotify: true } : {}))
  );
});
self.addEventListener('notificationclick', function(event) {
  event.notification.close();

  // Resolve to an absolute URL before comparing anything. The old check was
  // client.url.indexOf(url) !== -1 -- a substring test against the whole
  // address, which had two ways of sending you nowhere:
  //   * the fallback url '/' is a substring of EVERY url, so any open tab
  //     matched and was merely focused;
  //   * a match only ever called focus(), never navigating. So with a tab
  //     already open on Live Market, tapping a surge alert brought the app
  //     forward on whatever page it was showing and dropped the token.
  // Now: reuse a window if there is one, but NAVIGATE it to the target.
  var raw    = (event.notification.data && event.notification.data.url) || '/';
  var target = new URL(raw, self.location.origin).href;

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(windowClients) {
      var reusable = null;
      for (var i = 0; i < windowClients.length; i++) {
        var client = windowClients[i];
        // Never touch a window belonging to another site.
        if (client.url.indexOf(self.location.origin) !== 0) continue;
        if (client.url === target) {
          return 'focus' in client ? client.focus() : null;   // already there
        }
        if (!reusable) reusable = client;
      }
      if (reusable && 'navigate' in reusable) {
        return reusable.navigate(target)
          .then(function(c) { return c && c.focus ? c.focus() : null; })
          .catch(function() { return clients.openWindow ? clients.openWindow(target) : null; });
      }
      // No window to reuse, or a browser without navigate(): open the target
      // rather than focusing the wrong page. Landing on the right token in a
      // new window beats landing on the wrong one in an old window.
      return clients.openWindow ? clients.openWindow(target) : null;
    })
  );
});
