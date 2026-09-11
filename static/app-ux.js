/* OrcAgent shared UX/performance controller. */
(function(){
'use strict';
var prefetched=new Set();
function sameOriginUrl(href){try{var u=new URL(href,location.href);if(u.origin!==location.origin)return null;if(u.protocol!=='http:'&&u.protocol!=='https:')return null;return u}catch(e){return null}}
function navCandidate(a){if(!a||!a.href||a.hasAttribute('download')||(a.target&&a.target!=='_self'))return null;var u=sameOriginUrl(a.href);if(!u)return null;if(u.pathname.indexOf('/api/')===0)return null;if(/^javascript:/i.test(a.getAttribute('href')||''))return null;if(u.pathname===location.pathname&&u.search===location.search)return null;return u}
function prefetch(a){var u=navCandidate(a);if(!u)return;var key=u.pathname+u.search;if(prefetched.has(key))return;prefetched.add(key);var l=document.createElement('link');l.rel='prefetch';l.href=u.pathname+u.search;l.as='document';document.head.appendChild(l)}
function closestLink(e){var n=e.target;return n&&n.closest?n.closest('a[href]'):null}
['pointerover','touchstart','focusin'].forEach(function(type){document.addEventListener(type,function(e){prefetch(closestLink(e))},{passive:true,capture:true})});

/* Warm the pages users are most likely to open next. Slow/data-saver
   connections are deliberately excluded. Existing page-loader.js remains the
   only navigation progress UI, so there is no duplicate loader. */
function idlePrefetch(){var c=navigator.connection||navigator.mozConnection||navigator.webkitConnection;if(c&&(c.saveData||/2g/.test(c.effectiveType||'')))return;['/','/live-market','/wallet','/groups','/bot','/messages','/notifications'].forEach(function(h){var a=document.createElement('a');a.href=h;prefetch(a)})}
if('requestIdleCallback'in window)requestIdleCallback(idlePrefetch,{timeout:2400});else setTimeout(idlePrefetch,1600);

/* Images below the first viewport should not delay initial rendering. Keep
   explicitly eager images (logo/hero/token immediately visible) untouched. */
function tuneImage(img){if(!img||img.dataset.oaImgTuned==='1')return;img.dataset.oaImgTuned='1';if(!img.hasAttribute('decoding'))img.decoding='async';if(!img.hasAttribute('loading')&&!img.closest('.pt-nb-topbar,.oa-m-hero,.pf-hero,.pt-sheet'))img.loading='lazy'}
function tuneTree(root){if(root&&root.matches&&root.matches('img'))tuneImage(root);if(root&&root.querySelectorAll)root.querySelectorAll('img').forEach(tuneImage)}

/* Generic mobile modal lock. Old pages use several modal conventions: some
   toggle .open, others set display:flex directly. They now all freeze the
   document behind them and return to the exact same scroll position. */
var modalLocked=false,modalY=0;
function isVisible(el){if(!el)return false;if(el.classList.contains('open'))return true;var st=el.style&&el.style.display;if(st&&st!=='none')return true;try{return getComputedStyle(el).display!=='none'}catch(e){return false}}
function anyOpenModal(){var list=document.querySelectorAll('.s-modal,.modal-backdrop,.gd-modal-backdrop,[class*="modal-backdrop"],.modal-back,.w-modal-back');for(var i=0;i<list.length;i++){if(isVisible(list[i]))return true}return false}
function syncModalLock(){if(!window.matchMedia('(max-width:767px)').matches)return;if(document.documentElement.classList.contains('oa-groups-modal-open'))return;var open=anyOpenModal();if(open&&!modalLocked){modalLocked=true;modalY=window.scrollY||document.documentElement.scrollTop||0;document.documentElement.classList.add('oa-modal-open');document.body.style.position='fixed';document.body.style.top=(-modalY)+'px';document.body.style.left='0';document.body.style.right='0';document.body.style.width='100%'}else if(!open&&modalLocked){modalLocked=false;document.documentElement.classList.remove('oa-modal-open');document.body.style.position='';document.body.style.top='';document.body.style.left='';document.body.style.right='';document.body.style.width='';window.scrollTo(0,modalY)}}

/* Keep Messages' fullscreen thread truly fullscreen even though every normal
   page gets the shared bottom navigation. */
function watchThread(){var main=document.querySelector('.msgs-main');if(!main)return;function sync(){document.body.classList.toggle('oa-thread-open',main.classList.contains('thread-open'))}sync();if(window.MutationObserver)new MutationObserver(sync).observe(main,{attributes:true,attributeFilter:['class']})}

function ready(){document.body.classList.add('oa-shared-ux');tuneTree(document);syncModalLock();if(window.MutationObserver)new MutationObserver(function(ms){var modalMayHaveChanged=false;ms.forEach(function(m){if(m.type==='attributes')modalMayHaveChanged=true;m.addedNodes.forEach(function(n){if(n.nodeType===1){tuneTree(n);modalMayHaveChanged=true}})});if(modalMayHaveChanged)syncModalLock()}).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['class','style']});watchThread()}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ready);else ready();
})();
