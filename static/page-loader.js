(function(){
  /* page-loader.js is already present on the main OrcAgent screens, so it is
     the stable place to boot the shared UX layer without editing every
     server-rendered template separately. Guards keep fallback loaders safe. */
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
  function validLink(a){ return !!linkUrl(a); }

  /* ── Instant/warm navigation ──────────────────────────────────────────
     OrcAgent is still server-rendered. Replacing arbitrary page fragments
     would require every page script to gain an SPA lifecycle and risks
     duplicated polling/trading handlers. Instead, warm the *complete* next
     document as soon as intent is visible (touch/pointer/focus). On click we
     can install that already-fetched document immediately: no second network
     round-trip, while the target page's normal scripts still bootstrap from
     a clean document exactly as on a regular navigation.

     Entries are deliberately short-lived because these pages contain private,
     fast-changing account data. Nothing is persisted to localStorage, Cache
     Storage or a service worker. */
  var warm=new Map();
  var WARM_TTL=15000;
  var WARM_MAX=6;
  var navigating=false;

  function pruneWarm(){
    var now=Date.now();
    warm.forEach(function(v,k){ if(now-v.at>WARM_TTL) warm.delete(k); });
    while(warm.size>WARM_MAX){ warm.delete(warm.keys().next().value); }
  }

  function fetchDocument(u){
    var key=u.href;
    pruneWarm();
    var hit=warm.get(key);
    if(hit) return hit.promise;
    var entry={at:Date.now(),html:null,promise:null};
    entry.promise=fetch(key,{
      method:'GET',credentials:'include',redirect:'follow',
      headers:{'X-OrcAgent-Prefetch':'1','X-Requested-With':'OrcAgent-Warm-Navigation'}
    }).then(function(r){
      if(!r.ok) throw new Error('HTTP '+r.status);
      var ct=(r.headers.get('content-type')||'').toLowerCase();
      if(ct.indexOf('text/html')===-1) throw new Error('not html');
      return r.text().then(function(html){
        if(!html||html.toLowerCase().indexOf('<html')===-1) throw new Error('invalid html');
        entry.html=html;entry.at=Date.now();return html;
      });
    }).catch(function(err){ warm.delete(key); throw err; });
    warm.set(key,entry);pruneWarm();return entry.promise;
  }

  function warmLink(a){
    var u=linkUrl(a);if(!u)return;
    /* Avoid warming destructive/auth endpoints even if somebody later turns
       one into an anchor. Main page navigation is GET-only and safe. */
    if(/^\/(logout|disconnect|api)(\/|$)/i.test(u.pathname))return;
    fetchDocument(u).catch(function(){});
  }

  function installDocument(u,html){
    if(navigating)return;
    navigating=true;start();
    try{
      /* Change the visible URL first so relative links, history and scripts in
         the incoming document see the correct location while parsing. */
      history.pushState({oaInstant:true},'',u.href);
      document.open('text/html','replace');
      document.write(html);
      document.close();
      /* The incoming page loads page-loader.js again and owns completion. */
    }catch(err){
      navigating=false;
      location.href=u.href;
    }
  }

  /* Mobile intent arrives on pointerdown/touchstart roughly one finger-frame
     before click; desktop additionally gets pointerover/focus prefetch. */
  document.addEventListener('pointerdown',function(e){
    var a=e.target&&e.target.closest?e.target.closest('a[href]'):null;warmLink(a);
  },{capture:true,passive:true});
  document.addEventListener('touchstart',function(e){
    var a=e.target&&e.target.closest?e.target.closest('a[href]'):null;warmLink(a);
  },{capture:true,passive:true});
  document.addEventListener('pointerover',function(e){
    var a=e.target&&e.target.closest?e.target.closest('a[href]'):null;warmLink(a);
  },{capture:true,passive:true});
  document.addEventListener('focusin',function(e){
    var a=e.target&&e.target.closest?e.target.closest('a[href]'):null;warmLink(a);
  },true);

  document.addEventListener('click',function(e){
    if(e.defaultPrevented||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
    var a=e.target&&e.target.closest?e.target.closest('a[href]'):null;
    var u=linkUrl(a);
    if(!u)return;
    start();

    var hit=warm.get(u.href);
    /* Only intercept if the document is already warm. If it is still in
       flight, normal browser navigation wins; we never make a click slower
       just to force the instant-nav path. */
    if(hit&&hit.html){
      e.preventDefault();
      e.stopPropagation();
      installDocument(u,hit.html);
    }
  },true);

  /* Prime the five high-frequency app destinations once the current screen is
     interactive. requestIdleCallback keeps first paint/network priority for
     the page the user is actually looking at. */
  function primeCore(){
    ['/','/live-market','/messages','/wallet'].forEach(function(path){
      try{
        var u=new URL(path,location.origin);
        if(u.pathname!==location.pathname) fetchDocument(u).catch(function(){});
      }catch(_){ }
    });
  }
  if('requestIdleCallback' in window) requestIdleCallback(primeCore,{timeout:1800});
  else setTimeout(primeCore,900);

  addEventListener('beforeunload',start);

  /* Several older standalone templates register a bubble-phase pageshow
     handler that calls location.reload() whenever Safari restores them from
     bfcache. That makes Back/Forward needlessly re-download and rebuild the
     whole page. Capture-phase handling runs first and stops only those
     persisted restores; normal pageshow events still flow as before. Existing
     page polling resumes from the preserved JS state. */
  addEventListener('pageshow',function(e){
    finish();navigating=false;
    if(e.persisted){
      try{e.stopImmediatePropagation()}catch(_){ }
      document.dispatchEvent(new CustomEvent('oa:bfcache-restore'));
    }
  },true);
})();
