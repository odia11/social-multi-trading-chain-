/* OrcAgent mobile Home — approved feed-first social composition. */
(function(){
'use strict';
var path=location.pathname.replace(/\/+$/,'')||'/';
if(path!=='/'||!window.matchMedia('(max-width:767px)').matches)return;
var socialCss=document.createElement('link');socialCss.rel='stylesheet';socialCss.href='/static/home-social-feed.css?v=1';document.head.appendChild(socialCss);
function ready(fn){if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',fn);else fn()}
function ensureTagline(){var logo=document.querySelector('.pt-nb-logo');if(!logo)return;logo.setAttribute('aria-label','OrcAgent — Trade, Share, Grow')}
function removeOldHomeBlocks(){['oa-m-hero','oa-m-bot','oa-m-portfolio','oa-m-market-strip','oa-m-shortcuts','oa-m-feed-label'].forEach(function(id){var e=document.getElementById(id);if(e)e.remove()});document.querySelectorAll('.feed-bot-card,.botbar').forEach(function(e){e.style.display='none'})}
function makeTabs(wrap,composer){var old=document.getElementById('oa-social-tabs');if(old)old.remove();var tabs=document.createElement('nav');tabs.id='oa-social-tabs';tabs.className='oa-social-tabs';tabs.setAttribute('aria-label','Home feed');tabs.innerHTML='<button type="button" class="active" data-social-tab="foryou">For You</button><button type="button" data-social-tab="following">Following</button><button type="button" data-social-tab="groups">Groups</button><button type="button" data-social-tab="live">Live</button>';wrap.insertBefore(tabs,composer||wrap.firstChild);tabs.addEventListener('click',function(e){var b=e.target.closest('[data-social-tab]');if(!b)return;var name=b.dataset.socialTab;if(name==='groups'){location.href='/groups';return}if(name==='live'){location.href='/live-market';return}tabs.querySelectorAll('button').forEach(function(x){x.classList.toggle('active',x===b)});var native=document.querySelector('.feed-tab[data-tab="'+name+'"]');if(native)native.click()});return tabs}
function decoratePostButton(){var b=document.querySelector('#feed-composer .feed-composer-post');if(!b)return;b.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M22 2 11 13"/><path d="m22 2-7 20-4-9-9-4Z"/></svg><span>POST</span>';b.setAttribute('aria-label','Post update')}
function keepComposerOpen(c,t){if(!c||!t)return;c.classList.add('expanded');function syncCounter(){var x=document.getElementById('postText-counter');if(x){x.style.display='block';x.textContent=String((t.value||'').length)+'/500'}}syncCounter();['focus','input','click'].forEach(function(ev){t.addEventListener(ev,function(){c.classList.add('expanded','oa-post-open');syncCounter()})});t.addEventListener('blur',function(){setTimeout(function(){c.classList.add('expanded');c.classList.remove('oa-post-open')},100)});if(window.MutationObserver)new MutationObserver(function(){if(!c.classList.contains('expanded'))c.classList.add('expanded')}).observe(c,{attributes:true,attributeFilter:['class']})}
function openComposer(){var c=document.getElementById('feed-composer'),t=document.getElementById('postText');if(!c||!t)return;c.classList.add('expanded','oa-post-open');try{c.scrollIntoView({behavior:'smooth',block:'start'})}catch(e){c.scrollIntoView(true)}setTimeout(function(){t.focus();try{t.setSelectionRange(t.value.length,t.value.length)}catch(_){ }},150);try{history.replaceState(null,'',location.pathname)}catch(_){ }}
ready(function(){
  document.body.classList.add('oa-home-mobile','oa-home-social');document.documentElement.classList.add('oa-home-mobile-root');
  ensureTagline();removeOldHomeBlocks();
  var wrap=document.querySelector('.wrap'),composer=document.getElementById('feed-composer'),feed=document.getElementById('center-feed');if(!wrap||!composer)return;
  var nativeTabs=document.querySelector('.feed-tabs');if(nativeTabs)nativeTabs.style.display='none';
  var tabs=makeTabs(wrap,composer);tabs.insertAdjacentElement('afterend',composer);if(feed)composer.insertAdjacentElement('afterend',feed);
  var t=document.getElementById('postText');if(t)t.placeholder="What's on your mind?";
  keepComposerOpen(composer,t);decoratePostButton();
  addEventListener('oa:open-composer',openComposer);
  var q=new URLSearchParams(location.search);if(q.get('compose')==='1'||location.hash==='#feed-composer')setTimeout(openComposer,250);
});
})();
