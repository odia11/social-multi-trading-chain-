/* OrcAgent shared UX/performance controller. */
(function(){
'use strict';
var prefetched=new Set();
function sameOriginUrl(href){try{var u=new URL(href,location.href);if(u.origin!==location.origin)return null;if(u.protocol!=='http:'&&u.protocol!=='https:')return null;return u}catch(e){return null}}
function navCandidate(a){if(!a||!a.href||a.hasAttribute('download')||(a.target&&a.target!=='_self'))return null;var u=sameOriginUrl(a.href);if(!u)return null;if(u.pathname.indexOf('/api/')===0)return null;if(/^javascript:/i.test(a.getAttribute('href')||''))return null;if(u.pathname===location.pathname&&u.search===location.search)return null;return u}
function closestLink(e){var n=e.target;return n&&n.closest?n.closest('a[href]'):null}

/* HTML responses carry no-store because wallet/session pages are private.
   Prefetching those documents re-runs server work without a reusable cache
   entry. Warm ONLY versioned public route assets (never API or wallet data).
   Cross-document View Transitions keep the old page painted during navigation. */
var ROUTE_ASSETS={
  '/':['home-mobile.css?v=9','home-mobile-polish.css?v=7','home-composer-mobile.css?v=5','home-desktop.css?v=1','home-mobile.js?v=9','home-desktop.js?v=1'],
  '/wallet':['portfolio-redesign.css?v=7','portfolio-redesign.js?v=10','portfolio-assets.js?v=1'],
  '/live-market':['live-market-redesign.css?v=8','live-market-final.css?v=6','live-market-redesign.js?v=5','live-market-hotfix.js?v=8'],
  '/groups':['groups-redesign.css?v=1','groups-redesign.js?v=1']
};
function prefetch(a){
  var u=navCandidate(a);if(!u)return;
  var assets=ROUTE_ASSETS[u.pathname];if(!assets)return;
  if(navigator.connection&&navigator.connection.saveData)return;
  assets.forEach(function(asset){
    var key='/static/'+asset;if(prefetched.has(key))return;
    prefetched.add(key);
    var l=document.createElement('link');l.rel='prefetch';l.href=key;
    l.as=asset.indexOf('.css?')!==-1?'style':'script';document.head.appendChild(l);
  });
}
['pointerover','touchstart','focusin'].forEach(function(type){document.addEventListener(type,function(e){prefetch(closestLink(e))},{passive:true,capture:true})});

/* Images below the first viewport should not delay initial rendering. */
function tuneImage(img){
  if(!img||img.dataset.oaImgTuned==='1')return;
  img.dataset.oaImgTuned='1';
  if(!img.hasAttribute('decoding'))img.decoding='async';
  var aboveFold=!!img.closest('.pt-nb-topbar,.oa-m-hero,.pf-hero,.pt-sheet');
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
  tuneTree(document);syncModalLock();wireBotLanding();
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