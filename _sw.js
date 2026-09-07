
var _shown=null,_opened=null,_focused=null,_navigated=null,_clients=[];
var clients={matchAll:function(){return Promise.resolve(_clients);},
             openWindow:function(u){_opened=u;return Promise.resolve(null);}};
var listeners={};
var self={location:{origin:'https://orcagent.fun'},
          addEventListener:function(n,f){listeners[n]=f;},
          registration:{showNotification:function(t,o){_shown={title:t,opts:o};return Promise.resolve();}},
          clients:clients};
// OrcAgent service worker — receives Web Push events and shows notifications
// even when the site itself is closed.
self.addEventListener('install', function(event) {
  self.skipWaiting();
});
self.addEventListener('activate', function(event) {
  event.waitUntil(self.clients.claim());
});
self.addEventListener('push', function(event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) {}
  var title = data.title || 'OrcAgent';
  var body  = data.body  || '';
  var url   = data.url   || '/';
  event.waitUntil(
    self.registration.showNotification(title, {
      body: body,
      icon: '/favicon.svg?v=2',
      badge: '/favicon.svg?v=2',
      data: { url: url }
    })
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

function mkClient(url, canNavigate){
  var c={url:url, focus:function(){_focused=this.url;return Promise.resolve(this);}};
  if(canNavigate) c.navigate=function(u){_navigated=u;this.url=u;return Promise.resolve(this);};
  return c;
}
function reset(list){_clients=list;_opened=_focused=_navigated=null;}
function click(url){
  var waited=null;
  listeners['notificationclick']({notification:{close:function(){},data:url?{url:url}:null},
                                  waitUntil:function(p){waited=p;}});
  return waited.then(function(){return {opened:_opened,focused:_focused,navigated:_navigated};});
}
listeners['push']({data:{json:function(){return {title:'t',body:'b',url:'/live-market?mint=0xABC'};}},
                   waitUntil:function(p){return p;}});
var out={push_data_url:_shown.opts.data.url};
var TARGET='https://orcagent.fun/live-market?mint=0xABC';
Promise.resolve()
 .then(function(){reset([]);return click('/live-market?mint=0xABC');}).then(function(r){out.no_window=r;})
 .then(function(){reset([mkClient('https://orcagent.fun/live-market',true)]);return click('/live-market?mint=0xABC');}).then(function(r){out.open_on_live_market=r;})
 .then(function(){reset([mkClient('https://orcagent.fun/home',true)]);return click('/live-market?mint=0xABC');}).then(function(r){out.open_elsewhere=r;})
 .then(function(){reset([mkClient(TARGET,true)]);return click('/live-market?mint=0xABC');}).then(function(r){out.already_there=r;})
 .then(function(){reset([mkClient('https://orcagent.fun/home',false)]);return click('/live-market?mint=0xABC');}).then(function(r){out.no_navigate=r;})
 .then(function(){reset([mkClient('https://evil.example/x',true)]);return click('/live-market?mint=0xABC');}).then(function(r){out.foreign=r;})
 .then(function(){reset([mkClient('https://orcagent.fun/home',true)]);return click(null);}).then(function(r){out.no_url=r;})
 .then(function(){console.log(JSON.stringify(out));});
