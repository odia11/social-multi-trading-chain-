// OrcAgent service worker — public app-shell cache + Web Push.
// SECURITY INVARIANT: only /static/ GETs are cached. Authenticated HTML,
// API responses, balances, feeds and wallet data are always network-only.
var OA_STATIC_CACHE = 'orcagent-static-v6';
var OA_STATIC_BOOT = [
  '/static/app-ux.css?v=8',
  '/static/app-ux.js?v=7',
  '/static/mobile-bottom-nav.css?v=9',
  '/static/mobile-bottom-nav.js?v=9'
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
self.addEventListener('fetch', function(event) {
  var req=event.request;
  if(req.method!=='GET') return;
  var url;
  try{ url=new URL(req.url); }catch(_){ return; }
  if(url.origin!==self.location.origin || url.pathname.indexOf('/static/')!==0) return;
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
