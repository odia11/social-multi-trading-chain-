(function(){
  /* page-loader.js is already present on the main OrcAgent screens, so it is
     the stable place to boot the shared UX layer without editing every
     server-rendered template separately. Guards keep fallback loaders safe. */
  if(!document.getElementById('oa-app-ux-css')){
    var uxCss=document.createElement('link');uxCss.id='oa-app-ux-css';uxCss.rel='stylesheet';uxCss.href='/static/app-ux.css?v=2';document.head.appendChild(uxCss);
  }
  if(!document.getElementById('oa-app-ux-js')){
    var uxJs=document.createElement('script');uxJs.id='oa-app-ux-js';uxJs.src='/static/app-ux.js?v=2';uxJs.defer=true;document.head.appendChild(uxJs);
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
  function validLink(a){
    if(!a||!a.href||a.hasAttribute('download')||(a.target&&a.target!=='_self'))return false;
    if(/^javascript:/i.test(a.getAttribute('href')||''))return false;
    try{
      var u=new URL(a.href,location.href);
      if(u.origin!==location.origin||u.pathname.indexOf('/api/')===0)return false;
      if(u.pathname===location.pathname&&u.search===location.search)return false;
      return true;
    }catch(e){return false}
  }
  document.addEventListener('click',function(e){
    if(e.defaultPrevented||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
    var a=e.target&&e.target.closest?e.target.closest('a[href]'):null;
    if(validLink(a))start();
  },true);
  addEventListener('beforeunload',start);

  /* Several older standalone templates register a bubble-phase pageshow
     handler that calls location.reload() whenever Safari restores them from
     bfcache. That makes Back/Forward needlessly re-download and rebuild the
     whole page. Capture-phase handling runs first and stops only those
     persisted restores; normal pageshow events still flow as before. Existing
     page polling resumes from the preserved JS state. */
  addEventListener('pageshow',function(e){
    finish();
    if(e.persisted){
      try{e.stopImmediatePropagation()}catch(_){ }
      document.dispatchEvent(new CustomEvent('oa:bfcache-restore'));
    }
  },true);
})();
