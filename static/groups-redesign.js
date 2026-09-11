/* OrcAgent Groups redesign controller. Keeps the existing groups API and modal flows. */
(function(){
'use strict';
if(location.pathname.replace(/\/+$/,'')!=='/groups')return;
var _lockedScrollY=0;
function ready(fn){if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',fn);else fn()}
function lockPage(){
 if(document.documentElement.classList.contains('oa-groups-modal-open'))return;
 _lockedScrollY=window.scrollY||document.documentElement.scrollTop||0;
 document.documentElement.classList.add('oa-groups-modal-open');
 document.body.classList.add('oa-groups-modal-open');
 document.body.style.position='fixed';
 document.body.style.top=(-_lockedScrollY)+'px';
 document.body.style.left='0';
 document.body.style.right='0';
 document.body.style.width='100%';
}
function unlockPage(){
 if(!document.documentElement.classList.contains('oa-groups-modal-open'))return;
 document.documentElement.classList.remove('oa-groups-modal-open');
 document.body.classList.remove('oa-groups-modal-open');
 document.body.style.position='';
 document.body.style.top='';
 document.body.style.left='';
 document.body.style.right='';
 document.body.style.width='';
 window.scrollTo(0,_lockedScrollY);
}
function syncModalLock(){
 var open=Array.prototype.some.call(document.querySelectorAll('.modal-backdrop'),function(m){return m.classList.contains('open')});
 if(open)lockPage();else unlockPage();
}
function watchModals(){
 var mods=document.querySelectorAll('.modal-backdrop');
 if(!mods.length)return;
 if(window.MutationObserver){
   mods.forEach(function(m){new MutationObserver(syncModalLock).observe(m,{attributes:true,attributeFilter:['class','style']})});
 }
 document.addEventListener('click',function(){setTimeout(syncModalLock,0)},true);
 document.addEventListener('keydown',function(){setTimeout(syncModalLock,0)},true);
 syncModalLock();
}
ready(function(){
 document.body.classList.add('oa-groups-v2');
 document.title='Groups — OrcAgent';
 var title=document.querySelector('.page-title');if(title)title.textContent='Community Groups';
 var search=document.querySelector('.search-inp');if(search){search.placeholder='Search groups or tickers…';search.setAttribute('aria-label','Search groups')}
 var create=Array.prototype.slice.call(document.querySelectorAll('button')).find(function(b){return /create\s+group/i.test(b.textContent||'')});
 if(create){create.innerHTML='<span aria-hidden="true">＋</span> Create group';create.setAttribute('aria-label','Create a group')}
 /* Existing search handler performs server-side discovery. We only make clear/cancel behaviour reliable on mobile. */
 if(search){search.addEventListener('search',function(){if(!search.value&&typeof window._loadDiscoverGroups==='function')window._loadDiscoverGroups('')})}
 /* Re-label empty-state emoji visually without changing the loader logic. */
 var empty=document.querySelectorAll('.empty');empty.forEach(function(e){var ic=e.querySelector('.empty-icon');if(ic&&/💬/.test(ic.textContent||''))ic.textContent='◎'});
 watchModals();
});
})();
