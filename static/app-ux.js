/* OrcAgent shared UX/performance controller. */
(function(){
'use strict';
var prefetched=new Set();
var navWarmAt=new Map();
var navReadyAt=new Map();
var shellTimer=null;
var shellNode=null;
var APP_VERSION=(document.querySelector('meta[name=\"oa-app-version\"]')||{}).content||'';
function sameOriginUrl(href){try{var u=new URL(href,location.href);if(u.origin!==location.origin)return null;if(u.protocol!=='http:'&&u.protocol!=='https:')return null;return u}catch(e){return null}}
function navCandidate(a){if(!a||!a.href||a.hasAttribute('download')||a.hasAttribute('data-no-instant-nav')||(a.target&&a.target!=='_self'))return null;var u=sameOriginUrl(a.href);if(!u)return null;if(u.pathname.indexOf('/api/')===0)return null;if(/^javascript:/i.test(a.getAttribute('href')||''))return null;if(u.pathname===location.pathname&&u.search===location.search)return null;return u}
function closestLink(e){var n=e.target;return n&&n.closest?n.closest('a[href]'):null}

/* Route assets are warmed in the normal HTTP cache. The destination HTML is
   different: it can contain authenticated/session data, so it is never stored
   in Cache Storage/localStorage. We only send navigation intent to the service
   worker, which may hold one same-origin document briefly in RAM for this
   browser client and hand it to the subsequent native navigation. */
var ROUTE_ASSETS={
  '/':['home-mobile.css','home-mobile-polish.css','home-composer-mobile.css','home-desktop.css','home-mobile.js','home-desktop.js'],
  '/wallet':['portfolio-redesign.css','portfolio-history-redesign.css','portfolio-redesign.js','portfolio-history-redesign.js','approved-portfolio.js','portfolio-assets.js'],
  '/live-market':['live-market-redesign.css','live-market-final.css','live-market-redesign.js','live-market-hotfix.js'],
  '/groups':['groups-redesign.css','groups-redesign.js'],
  '/messages':['messages-ui.css','messages-inbox.css','messages-thread.css','messages-ui.js'],
  '/notifications':[],
  '/profile':['profile-v2.css','profile-gold-tip.css','tip-experience.css','tip-experience.js'],
  '/bot':['approved-bot.css'],
  '/settings':[]
};
var CORE_ROUTES=['/','/live-market','/wallet','/groups','/messages','/notifications','/profile','/bot','/settings'];
function staticBuildUrl(asset){
  asset=String(asset||'').split('?')[0].replace(/^\/+static\//,'').replace(/^\/+/,'');
  return '/static/'+asset+'?v='+encodeURIComponent(APP_VERSION||'1');
}
function warmAsset(asset,urgent){
  var key=staticBuildUrl(asset);if(prefetched.has(key))return;
  prefetched.add(key);
  var l=document.createElement('link');
  l.rel=urgent?'preload':'prefetch';l.href=key;
  l.as=asset.indexOf('.css')!==-1?'style':'script';
  if(urgent)l.fetchPriority='high';
  document.head.appendChild(l);
}
function routeKey(path){
  path=String(path||'').replace(/\/+$/,'')||'/';
  if(path==='/')return '/';
  var families=['/live-market','/wallet','/groups','/messages','/notifications','/profile','/bot','/settings'];
  for(var i=0;i<families.length;i++){
    var base=families[i];
    if(path===base||path.indexOf(base+'/')===0)return base;
  }
  return path;
}
function warmRoute(path,urgent){
  if(navigator.connection&&navigator.connection.saveData)return;
  (ROUTE_ASSETS[routeKey(path)]||[]).forEach(function(asset){warmAsset(asset,!!urgent)});
}
var NAV_WARM_SAFE_PREFIXES=[
  '/live-market','/wallet','/profile','/messages','/notifications','/groups',
  '/traders','/calls','/call','/leaderboard','/history',
  '/referrals','/settings','/auto-trading-bot','/bot','/token-launch',
  '/token-launches','/live-trades','/promote','/info'
];
function navWarmable(u){
  if(!u)return false;
  var p=u.pathname||'/';
  if(p==='/')return true;
  for(var i=0;i<NAV_WARM_SAFE_PREFIXES.length;i++){
    var base=NAV_WARM_SAFE_PREFIXES[i];
    if(p===base||p.indexOf(base+'/')===0)return true;
  }
  return false;
}
function navKey(u){return (u&&u.pathname?u.pathname:'')+(u&&u.search?u.search:'')}
function markNavReady(raw){
  var u=sameOriginUrl(raw);if(!u)return;
  navReadyAt.set(navKey(u),Date.now());
}
function isNavReady(u){
  var ts=navReadyAt.get(navKey(u))||0;
  if(!ts)return false;
  if(Date.now()-ts>7000){navReadyAt.delete(navKey(u));return false}
  return true;
}
if('serviceWorker' in navigator){
  navigator.serviceWorker.addEventListener('message',function(e){
    var d=e.data||{};
    if(d.type==='oa-nav-ready'&&typeof d.url==='string')markNavReady(d.url);
  });
}
function warmDocument(u){
  if(!navWarmable(u)||!('serviceWorker' in navigator))return;
  if(navigator.connection&&navigator.connection.saveData)return;
  var key=navKey(u),now=Date.now(),last=navWarmAt.get(key)||0;
  if(now-last<2500)return;
  navWarmAt.set(key,now);
  var msg={type:'oa-nav-prefetch',url:key};
  if(navigator.serviceWorker.controller){
    try{navigator.serviceWorker.controller.postMessage(msg)}catch(_){}
    return;
  }
  navigator.serviceWorker.ready.then(function(reg){
    if(reg&&reg.active)reg.active.postMessage(msg);
  }).catch(function(){});
}
function prefetch(a,warmHtml){
  var u=navCandidate(a);if(!u)return;
  warmRoute(u.pathname,true);
  if(warmHtml)warmDocument(u);
}
['pointerover','focusin'].forEach(function(type){
  document.addEventListener(type,function(e){prefetch(closestLink(e),false)},{passive:true,capture:true});
});
['pointerdown','touchstart'].forEach(function(type){
  document.addEventListener(type,function(e){prefetch(closestLink(e),true)},{passive:true,capture:true});
});

/* Background priming remains static-assets-only. Authenticated HTML is warmed
   only after explicit pointer/touch/focus intent, through the short-lived
   service-worker RAM handoff above. */
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

/* Native navigation stays authoritative. Paint the destination shell in the
   same click turn, before Safari can freeze the outgoing document for native
   paint holding. That prevents stale page content from lingering during a
   normal cross-document route change. */
function routeLabel(path){
  return {'/':'Home','/live-market':'Live Market','/wallet':'Portfolio','/groups':'Groups',
          '/messages':'Messages','/notifications':'Notifications','/profile':'Profile',
          '/bot':'Auto Trading','/settings':'Settings'}[routeKey(path)]||'OrcAgent';
}
function optimisticNav(path){
  document.querySelectorAll('.oa-bottom-nav a[href]').forEach(function(a){
    try{a.classList.toggle('active',(new URL(a.href,location.href)).pathname===path)}catch(_){}
  });
}
function showRouteShell(path){
  if(!window.matchMedia('(max-width:768px)').matches||document.hidden)return;
  if(shellNode&&shellNode.isConnected)return;
  var n=document.createElement('div');n.id='oa-route-shell';n.className='oa-route-shell show';
  n.setAttribute('aria-hidden','true');
  n.innerHTML='<div class="oa-route-shell-inner"><div class="oa-route-shell-title">'+routeLabel(path)+'</div>'+
    '<div class="oa-route-shell-hero"></div><div class="oa-route-shell-row"></div>'+
    '<div class="oa-route-shell-row short"></div><div class="oa-route-shell-card"></div>'+
    '<div class="oa-route-shell-card small"></div></div>';
  // Safari may freeze the outgoing document as soon as native navigation
  // starts. Make the shell visible synchronously so its paint-hold snapshot
  // contains the destination skeleton, never stale content from the old page.
  document.body.appendChild(n);shellNode=n;
}
function beginRoute(u){
  var path=u&&u.pathname?u.pathname:String(u||'/');
  var warm=!!(u&&u.pathname&&isNavReady(u));
  optimisticNav(path);
  clearTimeout(shellTimer);shellTimer=null;
  window.__oaSkipNextRouteShell=warm;
  // A warmed document is already waiting in service-worker RAM. Showing a
  // skeleton for that navigation creates the very flash we are trying to
  // remove. Cold routes still get the synchronous shell before Safari can
  // freeze the outgoing document.
  if(!warm)showRouteShell(path);
  setTimeout(function(){window.__oaSkipNextRouteShell=false},1200);
}
window.OrcAgentBeginRoute=beginRoute;
window.OrcAgentShowRouteShell=showRouteShell;
window.OrcAgentNavigationIsWarm=function(raw){var u=sameOriginUrl(raw);return !!(u&&isNavReady(u))};
function clearRouteShell(){
  clearTimeout(shellTimer);shellTimer=null;
  window.__oaSkipNextRouteShell=false;
  if(shellNode&&shellNode.parentNode)shellNode.parentNode.removeChild(shellNode);
  shellNode=null;
}
document.addEventListener('click',function(e){
  if(e.defaultPrevented||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
  var a=closestLink(e),u=navCandidate(a);if(!u)return;
  warmRoute(u.pathname,true);
  warmDocument(u);
  beginRoute(u);
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
var modalAttrObserver=window.MutationObserver?OrcPageLifecycle.mutationObserver(function(){syncModalLock()}):null;
function observeModal(el){if(!modalAttrObserver||!isModalNode(el))return;if(modalObserved&&modalObserved.has(el))return;if(modalObserved)modalObserved.add(el);modalAttrObserver.observe(el,{attributes:true,attributeFilter:['class','style']})}
function observeModalsIn(root){if(!root||root.nodeType!==1)return;if(isModalNode(root))observeModal(root);if(root.querySelectorAll)root.querySelectorAll(MODAL_SEL).forEach(observeModal)}

/* Keep Messages' fullscreen thread truly fullscreen even though every normal
   page gets the shared bottom navigation. */
function watchThread(){var main=document.querySelector('.msgs-main');if(!main)return;function sync(){document.body.classList.toggle('oa-thread-open',main.classList.contains('thread-open'))}sync();if(window.MutationObserver)OrcPageLifecycle.mutationObserver(sync).observe(main,{attributes:true,attributeFilter:['class']})}

function ready(){
  document.body.classList.add('oa-shared-ux');
  tuneTree(document);syncModalLock();scheduleRoutePrime();
  // Register the app-wide service worker for every signed-in/browser session.
  // Only /static/ persists in Cache Storage; intent-warmed HTML is short-lived
  // RAM only and APIs are never navigation-prefetched.
  if('serviceWorker' in navigator){
    window.addEventListener('load',function(){
      navigator.serviceWorker.register('/sw.js?v='+encodeURIComponent(APP_VERSION||'1')).catch(function(){});
    },{once:true});
  }
  document.querySelectorAll(MODAL_SEL).forEach(observeModal);
  if(window.MutationObserver)OrcPageLifecycle.mutationObserver(function(ms){
    var modalAdded=false;
    ms.forEach(function(m){m.addedNodes.forEach(function(n){if(n.nodeType!==1)return;tuneTree(n);observeModalsIn(n);if(isModalNode(n)||(n.querySelector&&n.querySelector(MODAL_SEL)))modalAdded=true})});
    if(modalAdded)syncModalLock();
  }).observe(document.body,{childList:true,subtree:true});
  watchThread();
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ready);else ready();
})();