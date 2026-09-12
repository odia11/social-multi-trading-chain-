/* OrcAgent shared UX/performance controller. */
(function(){
'use strict';
var prefetched=new Set();
function sameOriginUrl(href){try{var u=new URL(href,location.href);if(u.origin!==location.origin)return null;if(u.protocol!=='http:'&&u.protocol!=='https:')return null;return u}catch(e){return null}}
function navCandidate(a){if(!a||!a.href||a.hasAttribute('download')||(a.target&&a.target!=='_self'))return null;var u=sameOriginUrl(a.href);if(!u)return null;if(u.pathname.indexOf('/api/')===0)return null;if(/^javascript:/i.test(a.getAttribute('href')||''))return null;if(u.pathname===location.pathname&&u.search===location.search)return null;return u}
function prefetch(a){var u=navCandidate(a);if(!u)return;var key=u.pathname+u.search;if(prefetched.has(key))return;prefetched.add(key);var l=document.createElement('link');l.rel='prefetch';l.href=u.pathname+u.search;l.as='document';document.head.appendChild(l)}
function closestLink(e){var n=e.target;return n&&n.closest?n.closest('a[href]'):null}

/* Warm only the page the user is actually showing intent to open. The old
   idle routine fetched seven authenticated HTML pages after every navigation,
   which competed with the page's own API calls on the single app worker and
   made "prefetching" feel like lag. */
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
function syncModalLock(){if(!window.matchMedia('(max-width:767px)').matches)return;if(document.documentElement.classList.contains('oa-groups-modal-open'))return;var open=anyOpenModal();if(open&&!modalLocked){modalLocked=true;modalY=window.scrollY||document.documentElement.scrollTop||0;document.documentElement.classList.add('oa-modal-open');document.body.style.position='fixed';document.body.style.top=(-modalY)+'px';document.body.style.left='0';document.body.style.right='0';document.body.style.width='100%'}else if(!open&&modalLocked){modalLocked=false;document.documentElement.classList.remove('oa-modal-open');document.body.style.position='';document.body.style.top='';document.body.style.left='';document.body.style.right='';document.body.style.width='';window.scrollTo(0,modalY)}}

/* Observe class/style only on modal shells. The old observer watched those
   attributes on every node in the app; live charts, feeds and counters mutate
   them constantly, causing needless main-thread work. */
var modalObserved=typeof WeakSet!=='undefined'?new WeakSet():null;
var modalAttrObserver=window.MutationObserver?new MutationObserver(function(){syncModalLock()}):null;
function observeModal(el){if(!modalAttrObserver||!isModalNode(el))return;if(modalObserved&&modalObserved.has(el))return;if(modalObserved)modalObserved.add(el);modalAttrObserver.observe(el,{attributes:true,attributeFilter:['class','style']})}
function observeModalsIn(root){if(!root||root.nodeType!==1)return;if(isModalNode(root))observeModal(root);if(root.querySelectorAll)root.querySelectorAll(MODAL_SEL).forEach(observeModal)}

/* Keep Messages' fullscreen thread truly fullscreen even though every normal
   page gets the shared bottom navigation. */
function watchThread(){var main=document.querySelector('.msgs-main');if(!main)return;function sync(){document.body.classList.toggle('oa-thread-open',main.classList.contains('thread-open'))}sync();if(window.MutationObserver)new MutationObserver(sync).observe(main,{attributes:true,attributeFilter:['class']})}

function ready(){
  document.body.classList.add('oa-shared-ux');
  tuneTree(document);syncModalLock();
  document.querySelectorAll(MODAL_SEL).forEach(observeModal);
  if(window.MutationObserver)new MutationObserver(function(ms){
    var modalAdded=false;
    ms.forEach(function(m){m.addedNodes.forEach(function(n){if(n.nodeType!==1)return;tuneTree(n);observeModalsIn(n);if(isModalNode(n)||(n.querySelector&&n.querySelector(MODAL_SEL)))modalAdded=true})});
    if(modalAdded)syncModalLock();
  }).observe(document.body,{childList:true,subtree:true});
  watchThread();
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ready);else ready();
})();
