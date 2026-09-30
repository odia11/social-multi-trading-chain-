/* OrcAgent shared UX/performance controller. */
(function(){
'use strict';
var prefetched=new Set();
var shellTimer=null;
var shellNode=null;
var APP_VERSION=(document.querySelector('meta[name=\"oa-app-version\"]')||{}).content||'';
function sameOriginUrl(href){try{var u=new URL(href,location.href);if(u.origin!==location.origin)return null;if(u.protocol!=='http:'&&u.protocol!=='https:')return null;return u}catch(e){return null}}
function navCandidate(a){if(!a||!a.href||a.hasAttribute('download')||(a.target&&a.target!=='_self'))return null;var u=sameOriginUrl(a.href);if(!u)return null;if(u.pathname.indexOf('/api/')===0)return null;if(/^javascript:/i.test(a.getAttribute('href')||''))return null;if(u.pathname===location.pathname&&u.search===location.search)return null;return u}
function closestLink(e){var n=e.target;return n&&n.closest?n.closest('a[href]'):null}

/* HTML responses carry no-store because wallet/session pages are private.
   Prefetching those documents re-runs server work without a reusable cache
   entry. Warm ONLY versioned public route assets (never API or wallet data).
   Cross-document View Transitions keep the old page painted during navigation. */
var ROUTE_ASSETS={
  '/':['home-mobile.css?v=13','home-mobile-polish.css?v=8','home-composer-mobile.css?v=7','home-desktop.css?v=1','home-mobile.js?v=11','home-desktop.js?v=1'],
  '/wallet':['portfolio-redesign.css?v={app}','portfolio-history-redesign.css?v={app}','portfolio-redesign.js?v={app}','portfolio-history-redesign.js?v={app}','approved-portfolio.js?v={app}','portfolio-assets.js?v=1'],
  '/live-market':['live-market-redesign.css?v=8','live-market-final.css?v=6','live-market-redesign.js?v=5','live-market-hotfix.js?v=8'],
  '/groups':['groups-redesign.css?v=1','groups-redesign.js?v=1'],
  '/messages':['messages-ui.css?v=1','messages-inbox.css?v=1','messages-thread.css?v=2','messages-ui.js?v=4'],
  '/notifications':[],
  '/profile':['profile-v2.css?v={app}','profile-gold-tip.css?v={app}','tip-experience.css?v={app}','tip-experience.js?v={app}'],
  '/bot':['approved-bot.css?v={app}'],
  '/settings':[]
};
var CORE_ROUTES=['/','/live-market','/wallet','/groups','/messages','/notifications','/profile','/bot','/settings'];
function warmAsset(asset,urgent){
  asset=String(asset||'').replace(/\{app\}/g,encodeURIComponent(APP_VERSION||'1'));
  var key='/static/'+asset;if(prefetched.has(key))return;
  prefetched.add(key);
  var l=document.createElement('link');
  l.rel=urgent?'preload':'prefetch';l.href=key;
  l.as=asset.indexOf('.css')!==-1?'style':'script';
  if(urgent)l.fetchPriority='high';
  document.head.appendChild(l);
}
function warmRoute(path,urgent){
  if(navigator.connection&&navigator.connection.saveData)return;
  (ROUTE_ASSETS[path]||[]).forEach(function(asset){warmAsset(asset,!!urgent)});
}
function prefetch(a){
  var u=navCandidate(a);if(!u)return;
  warmRoute(u.pathname,true);
}
['pointerover','touchstart','focusin'].forEach(function(type){
  document.addEventListener(type,function(e){prefetch(closestLink(e))},{passive:true,capture:true});
});

/* X/Instagram-style route chunk warming: after the CURRENT page is interactive,
   cache only public versioned CSS/JS for the routes users switch between most.
   We deliberately do NOT fetch private HTML, API responses, balances or feeds. */
function primeRouteAssets(){
  if(navigator.connection&&navigator.connection.saveData)return;
  var i=0;
  function one(){
    if(i>=CORE_ROUTES.length)return;
    var path=CORE_ROUTES[i++];
    if(path!==location.pathname)warmRoute(path,false);
    setTimeout(one,75);
  }
  one();
}
function scheduleRoutePrime(){
  var run=function(){primeRouteAssets()};
  if('requestIdleCallback' in window)requestIdleCallback(run,{timeout:1400});
  else setTimeout(run,650);
}

/* Native navigation stays authoritative. We only make the shell react
   immediately and show a lightweight route skeleton if the server takes long
   enough that a user would otherwise see a frozen old screen. */
function routeLabel(path){
  return {'/':'Home','/live-market':'Live Market','/wallet':'Portfolio','/groups':'Groups',
          '/messages':'Messages','/notifications':'Notifications','/profile':'Profile',
          '/bot':'Auto Trading','/settings':'Settings'}[path]||'OrcAgent';
}
function optimisticNav(path){
  document.querySelectorAll('.oa-bottom-nav a[href]').forEach(function(a){
    try{a.classList.toggle('active',(new URL(a.href,location.href)).pathname===path)}catch(_){}
  });
}
function showRouteShell(path){
  if(!window.matchMedia('(max-width:768px)').matches||document.hidden)return;
  if(shellNode&&shellNode.isConnected)return;
  var n=document.createElement('div');n.id='oa-route-shell';n.className='oa-route-shell';
  n.setAttribute('aria-hidden','true');
  n.innerHTML='<div class="oa-route-shell-inner"><div class="oa-route-shell-title">'+routeLabel(path)+'</div>'+
    '<div class="oa-route-shell-hero"></div><div class="oa-route-shell-row"></div>'+
    '<div class="oa-route-shell-row short"></div><div class="oa-route-shell-card"></div>'+
    '<div class="oa-route-shell-card small"></div></div>';
  document.body.appendChild(n);shellNode=n;
  requestAnimationFrame(function(){n.classList.add('show')});
}
function beginRoute(path){
  optimisticNav(path);
  clearTimeout(shellTimer);
  shellTimer=setTimeout(function(){showRouteShell(path)},120);
}
function clearRouteShell(){
  clearTimeout(shellTimer);shellTimer=null;
  if(shellNode&&shellNode.parentNode)shellNode.parentNode.removeChild(shellNode);
  shellNode=null;
}
document.addEventListener('click',function(e){
  if(e.defaultPrevented||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
  var a=closestLink(e),u=navCandidate(a);if(!u)return;
  warmRoute(u.pathname,true);
  beginRoute(u.pathname);
},true);
window.addEventListener('pageshow',clearRouteShell,true);
window.addEventListener('pagehide',function(){clearTimeout(shellTimer)},true);

/* Images below the first viewport should not delay initial rendering. */
function tuneImage(img){
  if(!img||img.dataset.oaImgTuned==='1')return;
  img.dataset.oaImgTuned='1';
  if(!img.hasAttribute('decoding'))img.decoding='async';
  var avatar=!!img.closest('.fc-avatar,.feed-composer-avatar,.fc-ri-avatar');
  var aboveFold=avatar||!!img.closest('.pt-nb-topbar,.oa-m-hero,.pf-hero,.pt-sheet');
  if(!img.hasAttribute('loading')&&!aboveFold)img.loading='lazy';
  if(!aboveFold&&!img.hasAttribute('fetchpriority')){try{img.fetchPriority='low'}catch(_){ }}
}
function tuneTree(root){if(root&&root.matches&&root.matches('img'))tuneImage(root);if(root&&root.querySelectorAll)root.querySelectorAll('img').forEach(tuneImage)}

/* Stop decorative CSS animation work while Safari/iOS has the page hidden. */
function syncVisibility(){document.documentElement.classList.toggle('oa-page-hidden',document.hidden)}
document.addEventListener('visibilitychange',syncVisibility,{passive:true});syncVisibility();

/* Generic mobile modal lock. */
var MODAL_SEL='.s-modal,.modal-backdrop,.gd-modal-backdrop,[class*="modal-backdrop"],.modal-back,.w-modal-back';
var modalLocked=false,modalY=0;
function isModalNode(el){return !!(el&&el.matches&&el.matches(MODAL_SEL))}
function isVisible(el){if(!el)return false;if(el.classList.contains('open'))return true;var st=el.style&&el.style.display;if(st&&st!=='none')return true;try{return getComputedStyle(el).display!=='none'}catch(e){return false}}
function anyOpenModal(){var list=document.querySelectorAll(MODAL_SEL);for(var i=0;i<list.length;i++){if(isVisible(list[i]))return true}return false}
function syncModalLock(){if(!window.matchMedia('(max-width:768px)').matches)return;if(document.documentElement.classList.contains('oa-groups-modal-open'))return;var open=anyOpenModal();if(open&&!modalLocked){modalLocked=true;modalY=window.scrollY||document.documentElement.scrollTop||0;document.documentElement.classList.add('oa-modal-open');document.body.style.position='fixed';document.body.style.top=(-modalY)+'px';document.body.style.left='0';document.body.style.right='0';document.body.style.width='100%'}else if(!open&&modalLocked){modalLocked=false;document.documentElement.classList.remove('oa-modal-open');document.body.style.position='';document.body.style.top='';document.body.style.left='';document.body.style.right='';document.body.style.width='';window.scrollTo(0,modalY)}}

/* Observe class/style only on modal shells. */
var modalObserved=typeof WeakSet!=='undefined'?new WeakSet():null;
var modalAttrObserver=window.MutationObserver?new MutationObserver(function(){syncModalLock()}):null;
function observeModal(el){if(!modalAttrObserver||!isModalNode(el))return;if(modalObserved&&modalObserved.has(el))return;if(modalObserved)modalObserved.add(el);modalAttrObserver.observe(el,{attributes:true,attributeFilter:['class','style']})}
function observeModalsIn(root){if(!root||root.nodeType!==1)return;if(isModalNode(root))observeModal(root);if(root.querySelectorAll)root.querySelectorAll(MODAL_SEL).forEach(observeModal)}

/* Keep Messages' fullscreen thread truly fullscreen even though every normal
   page gets the shared bottom navigation. */
function watchThread(){var main=document.querySelector('.msgs-main');if(!main)return;function sync(){document.body.classList.toggle('oa-thread-open',main.classList.contains('thread-open'))}sync();if(window.MutationObserver)new MutationObserver(sync).observe(main,{attributes:true,attributeFilter:['class']})}

/* The AI-bot landing CTA must open Bot Overview itself, never Live Market.
   Do it in-place so iOS/PWA navigation, query stripping or cached route state
   cannot send the user somewhere else. */
function wireBotLanding(){
  var cta=document.getElementById('bot-start-landing');
  if(!cta||cta.dataset.oaBotWired==='1')return;
  cta.dataset.oaBotWired='1';
  cta.addEventListener('click',function(e){
    e.preventDefault();
    e.stopPropagation();
    var intro=document.getElementById('bot-intro');
    var dash=document.getElementById('bot-dashboard');
    if(!dash){window.location.href='/bot?view=trading';return;}
    if(intro)intro.style.display='none';
    dash.classList.add('active');
    try{window._showTrading=true}catch(_){ }
    try{history.replaceState({oaBotTrading:true},'', '/bot?view=trading')}catch(_){ }
    if(typeof window.loadOverview==='function')window.loadOverview();
    window.scrollTo({top:0,behavior:'instant'});
  },true);
}

function ready(){
  document.body.classList.add('oa-shared-ux');
  tuneTree(document);syncModalLock();wireBotLanding();scheduleRoutePrime();
  // Register the app-wide service worker for every signed-in/browser session,
  // not only users who happened to open notification settings. It caches only
  // public /static/ assets; private HTML/API data remain network-only.
  if('serviceWorker' in navigator){
    window.addEventListener('load',function(){
      navigator.serviceWorker.register('/sw.js').catch(function(){});
    },{once:true});
  }
  document.querySelectorAll(MODAL_SEL).forEach(observeModal);
  if(window.MutationObserver)new MutationObserver(function(ms){
    var modalAdded=false;
    ms.forEach(function(m){m.addedNodes.forEach(function(n){if(n.nodeType!==1)return;tuneTree(n);observeModalsIn(n);if(isModalNode(n)||(n.querySelector&&n.querySelector(MODAL_SEL)))modalAdded=true})});
    if(modalAdded)syncModalLock();
    wireBotLanding();
  }).observe(document.body,{childList:true,subtree:true});
  watchThread();
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ready);else ready();
})();