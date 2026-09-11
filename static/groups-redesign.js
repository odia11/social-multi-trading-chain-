/* OrcAgent Groups redesign controller. Keeps the existing groups API and modal flows. */
(function(){
'use strict';
if(location.pathname.replace(/\/+$/,'')!=='/groups')return;
function ready(fn){if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',fn);else fn()}
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
});
})();
