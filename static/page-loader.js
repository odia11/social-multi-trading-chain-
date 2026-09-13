(function(){
  /* Shared OrcAgent navigation UX. Keep page transitions fast without ever
     replacing a live document with document.write(), because several standalone
     screens bootstrap inline JS during parser execution (Messages, Groups,
     Live Market, Portfolio, profiles, etc.). Native navigation guarantees every
     page gets its full lifecycle; prefetching still warms network/server/cache. */
  if(!document.getElementById('oa-app-ux-css')){
    var uxCss=document.createElement('link');uxCss.id='oa-app-ux-css';uxCss.rel='stylesheet';uxCss.href='/static/app-ux.css?v=3';document.head.appendChild(uxCss);
  }
  if(!document.getElementById('oa-app-ux-js')){
    var uxJs=document.createElement('script');uxJs.id='oa-app-ux-js';uxJs.src='/static/app-ux.js?v=3';uxJs.defer=true;document.head.appendChild(uxJs);
  }

  var b=document.createElement('div');
  b.id='pgl-bar';
  b.style.cssText='position:fixed;top:0;left:0;height:2px;width:0;background:#f7b955;z-index:99999;transition:width .18s ease,opacity .22s ease;box-shadow:0 0 8px rgba(247,185,85,.35);pointer-events:none';
  document.documentElement.appendChild(b);
  var p=0,t=null,running=false;
  function start(){
    if(running)return;
    running=true;p=12;b.style.transition='none';b.style.width=p+'%';b.style.opacity='1';
    requestAnimationFrame(function(){b.style.transition='width .18s ease,opacity .22s ease'});
    clearInterval(t);t=setInterval(function(){p+=(88-p)*.11;b.style.width=p+'%'},120);
  }
  function finish(){
    running=false;clearInterval(t);t=null;b.style.width='100%';b.style.opacity='0';
    setTimeout(function(){if(!running)b.style.width='0'},260);
  }

  function linkUrl(a){
    if(!a||!a.href||a.hasAttribute('download')||(a.target&&a.target!=='_self'))return null;
    if(a.hasAttribute('data-no-instant-nav'))return null;
    if(/^javascript:/i.test(a.getAttribute('href')||''))return null;
    try{
      var u=new URL(a.href,location.href);
      if(u.origin!==location.origin||u.pathname.indexOf('/api/')===0)return null;
      if(u.pathname===location.pathname&&u.search===location.search)return null;
      return u;
    }catch(e){return null}
  }

  /* Short-lived in-memory warm cache. We intentionally never install this HTML
     into document; the fetch only warms DNS/TLS/server work and browser HTTP
     cache where applicable. Nothing private is persisted across restarts. */
  var warm=new Map();
  var WARM_TTL=15000;
  var WARM_MAX=6;
  function pruneWarm(){
    var now=Date.now();
    warm.forEach(function(v,k){if(now-v.at>WARM_TTL)warm.delete(k)});
    while(warm.size>WARM_MAX)warm.delete(warm.keys().next().value);
  }
  function fetchDocument(u){
    var key=u.href;pruneWarm();
    var hit=warm.get(key);if(hit)return hit.promise;
    var entry={at:Date.now(),promise:null};
    entry.promise=fetch(key,{
      method:'GET',credentials:'include',redirect:'follow',
      headers:{'X-OrcAgent-Prefetch':'1','X-Requested-With':'OrcAgent-Warm-Navigation'}
    }).then(function(r){
      if(!r.ok)throw new Error('HTTP '+r.status);
      var ct=(r.headers.get('content-type')||'').toLowerCase();
      if(ct.indexOf('text/html')===-1)throw new Error('not html');
      entry.at=Date.now();return true;
    }).catch(function(err){warm.delete(key);throw err});
    warm.set(key,entry);pruneWarm();return entry.promise;
  }
  function warmLink(a){
    var u=linkUrl(a);if(!u)return;
    if(/^\/(logout|disconnect|api)(\/|$)/i.test(u.pathname))return;
    fetchDocument(u).catch(function(){});
  }

  ['pointerdown','pointerover','focusin'].forEach(function(evt){
    document.addEventListener(evt,function(e){
      var a=e.target&&e.target.closest?e.target.closest('a[href]'):null;warmLink(a);
    },true);
  });
  document.addEventListener('touchstart',function(e){
    var a=e.target&&e.target.closest?e.target.closest('a[href]'):null;warmLink(a);
  },{capture:true,passive:true});

  /* Never intercept navigation. Native page load is the reliability boundary:
     every screen gets parser execution, DOMContentLoaded, module setup,
     polling, token-card hydration and page-specific API bootstraps normally. */
  document.addEventListener('click',function(e){
    if(e.defaultPrevented||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
    var a=e.target&&e.target.closest?e.target.closest('a[href]'):null;
    if(linkUrl(a))start();
  },true);

  function primeCore(){
    ['/','/live-market','/messages','/wallet','/groups'].forEach(function(path){
      try{
        var u=new URL(path,location.origin);
        if(u.pathname!==location.pathname)fetchDocument(u).catch(function(){});
      }catch(_){ }
    });
  }
  if('requestIdleCallback' in window)requestIdleCallback(primeCore,{timeout:1800});
  else setTimeout(primeCore,900);

  addEventListener('beforeunload',start);
  addEventListener('pageshow',function(e){
    finish();
    if(e.persisted){
      try{e.stopImmediatePropagation()}catch(_){ }
      document.dispatchEvent(new CustomEvent('oa:bfcache-restore'));
    }
  },true);
})();
