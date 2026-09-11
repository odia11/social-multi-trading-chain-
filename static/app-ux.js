/* OrcAgent shared UX/performance controller. */
(function(){
'use strict';
var prefetched=new Set();
function sameOriginUrl(href){try{var u=new URL(href,location.href);if(u.origin!==location.origin)return null;if(u.protocol!=='http:'&&u.protocol!=='https:')return null;return u}catch(e){return null}}
function navCandidate(a){if(!a||!a.href||a.hasAttribute('download')||(a.target&&a.target!=='_self'))return null;var u=sameOriginUrl(a.href);if(!u)return null;if(u.pathname.indexOf('/api/')===0)return null;if(/^javascript:/i.test(a.getAttribute('href')||''))return null;if(u.pathname===location.pathname&&u.search===location.search&&u.hash===(location.hash||''))return null;if(u.pathname===location.pathname&&u.search===location.search&&u.hash!==(location.hash||''))return null;return u}
function prefetch(a){var u=navCandidate(a);if(!u)return;var key=u.pathname+u.search;if(prefetched.has(key))return;prefetched.add(key);var l=document.createElement('link');l.rel='prefetch';l.href=u.pathname+u.search;l.as='document';document.head.appendChild(l)}
function closestLink(e){var n=e.target;return n&&n.closest?n.closest('a[href]'):null}
['pointerover','touchstart','focusin'].forEach(function(type){document.addEventListener(type,function(e){prefetch(closestLink(e))},{passive:true,capture:true})});

function idlePrefetch(){var c=navigator.connection||navigator.mozConnection||navigator.webkitConnection;if(c&&(c.saveData||/2g/.test(c.effectiveType||'')))return;['/','/live-market','/wallet','/groups','/bot','/messages','/notifications'].forEach(function(h){var a=document.createElement('a');a.href=h;prefetch(a)})}
if('requestIdleCallback'in window)requestIdleCallback(idlePrefetch,{timeout:2400});else setTimeout(idlePrefetch,1600);

/* Lightweight navigation feedback, like native social apps. This does not
   hijack routing; it only covers the server roundtrip visually. */
var bar=document.createElement('div');bar.className='oa-route-progress';bar.setAttribute('aria-hidden','true');
function mountBar(){if(!bar.isConnected)document.body.appendChild(bar)}
function showBar(){mountBar();bar.classList.remove('done');requestAnimationFrame(function(){bar.classList.add('show')})}
function doneBar(){if(!bar.isConnected)return;bar.classList.add('done');bar.classList.remove('show');setTimeout(function(){bar.classList.remove('done')},350)}
document.addEventListener('click',function(e){if(e.defaultPrevented||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;var a=closestLink(e),u=navCandidate(a);if(!u)return;if(a&&a.dataset&&a.dataset.noProgress)return;showBar()},true);
window.addEventListener('pageshow',doneBar);
window.addEventListener('pagehide',function(){if(bar.isConnected)bar.classList.remove('done')});

/* Images below the first viewport should not delay initial rendering. Keep
   explicitly eager images (logo/hero/token immediately visible) untouched. */
function tuneImage(img){if(!img||img.dataset.oaImgTuned==='1')return;img.dataset.oaImgTuned='1';if(!img.hasAttribute('decoding'))img.decoding='async';if(!img.hasAttribute('loading')&&!img.closest('.pt-nb-topbar,.oa-m-hero,.pf-hero,.pt-sheet'))img.loading='lazy'}
function tuneTree(root){if(root&&root.matches&&root.matches('img'))tuneImage(root);if(root&&root.querySelectorAll)root.querySelectorAll('img').forEach(tuneImage)}

/* Generic mobile modal lock. Several older pages had a scrollable modal but
   never froze the document behind it, which lets iOS scroll/refresh the page
   underneath. Groups already has a specialised lock, so we do not fight it. */
var modalLocked=false,modalY=0;
function anyOpenModal(){return !!document.querySelector('.s-modal.open,.modal-backdrop.open,.gd-modal-backdrop.open,[class*="modal-backdrop"].open')}
function syncModalLock(){if(!window.matchMedia('(max-width:767px)').matches)return;if(document.documentElement.classList.contains('oa-groups-modal-open'))return;var open=anyOpenModal();if(open&&!modalLocked){modalLocked=true;modalY=window.scrollY||document.documentElement.scrollTop||0;document.documentElement.classList.add('oa-modal-open');document.body.style.position='fixed';document.body.style.top=(-modalY)+'px';document.body.style.left='0';document.body.style.right='0';document.body.style.width='100%'}else if(!open&&modalLocked){modalLocked=false;document.documentElement.classList.remove('oa-modal-open');document.body.style.position='';document.body.style.top='';document.body.style.left='';document.body.style.right='';document.body.style.width='';window.scrollTo(0,modalY)}}

/* Keep Messages' fullscreen thread truly fullscreen even though every normal
   page gets the shared bottom navigation. */
function watchThread(){var main=document.querySelector('.msgs-main');if(!main)return;function sync(){document.body.classList.toggle('oa-thread-open',main.classList.contains('thread-open'))}sync();if(window.MutationObserver)new MutationObserver(sync).observe(main,{attributes:true,attributeFilter:['class']})}

function ready(){document.body.classList.add('oa-shared-ux');tuneTree(document);syncModalLock();if(window.MutationObserver)new MutationObserver(function(ms){var modalMayHaveChanged=false;ms.forEach(function(m){if(m.type==='attributes')modalMayHaveChanged=true;m.addedNodes.forEach(function(n){if(n.nodeType===1){tuneTree(n);modalMayHaveChanged=true}})});if(modalMayHaveChanged)syncModalLock()}).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['class']});watchThread()}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ready);else ready();
})();
