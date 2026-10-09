(()=>{'use strict';
function boot(){
if(window._orcPromotionPlacements)return;window._orcPromotionPlacements=true;
const lifecycle=window.OrcPageLifecycle,scope=lifecycle.createScope('paid-promotions',document.body);
const request=(...a)=>scope?scope.fetch(...a):fetch(...a),timers=new Map();let feedAd=null,closed=false,pending=false;
const make=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
function event(receipt,type){if(document.hidden||closed)return;request('/api/promote/event',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="promo-csrf-token"],meta[name="csrf-token"]')?.content||''},body:JSON.stringify({receipt,event:type}),keepalive:true}).catch(()=>{});}
const observer=scope.intersectionObserver(observe,{threshold:[0,.5]});
function observe(entries){entries.forEach(entry=>{const e=entry.target;if(entry.intersectionRatio>=.5&&!document.hidden&&!e.dataset.viewed&&!viewedReceipts.has(e.dataset.receipt)){if(!timers.has(e)){const h=setTimeout(()=>{timers.delete(e);if(e.isConnected&&!document.hidden&&!viewedReceipts.has(e.dataset.receipt)){e.dataset.viewed='1';viewedReceipts.add(e.dataset.receipt);event(e.dataset.receipt,'view');observer.unobserve(e);}},1000);timers.set(e,h);}}else{clearTimeout(timers.get(e));timers.delete(e);}});}
function ad(p){const e=make('article',null,'promo-ad');e.dataset.receipt=p.receipt;const logo=make('span',(p.symbol||'?').slice(0,2),'promo-logo');if(p.logo&&/^https:\/\//.test(p.logo)){const img=make('img');img.src=p.logo;img.alt='';img.className='promo-logo';img.addEventListener('error',()=>img.replaceWith(logo),{once:true});e.append(img);}else e.append(logo);const content=make('div',null,'promo-ad-content'),title=make('strong',p.symbol,'promo-ad-title');const labels=make('div',null,'promo-ad-labels');labels.append(make('span',p.demo?'Demo':'Sponsored','promo-sponsored'));const heading=make('div',null,'promo-ad-heading');heading.append(title);if(p.active){const badge=make('span',null,'promo-active');badge.title='Active promotion';badge.setAttribute('aria-label','Active promotion');badge.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="m12 1 3 2 3.6.4 1.1 3.4 2.3 2.8-1.1 3.4.3 3.6-3 2-2 3-3.6-.3L9.2 22l-2.8-2.3L3 18.6 2.6 15 1 12l2-3 .4-3.6 3.4-1.1L9.6 2z"/><path d="m7.5 12 3 3 6-6" fill="none" stroke="#082b1c" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';heading.append(badge);}heading.append(labels);content.append(heading,make('p',p.description));const link=make('a','View token');link.href='/live-market?mint='+encodeURIComponent(p.mint);link.addEventListener('click',()=>{if(e.dataset.viewed)event(p.receipt,'click');});content.append(link);e.append(content);observer.observe(e);return e;}
const carousels=new Map(),viewedReceipts=new Set();
const carouselObserver=scope.intersectionObserver(entries=>entries.forEach(entry=>{const s=carousels.get(entry.target);if(s)s.visible=entry.isIntersecting;}),{threshold:0});
function pauseFor(s){s.resumeAt=performance.now()+5000;}
function sizeCarousel(s){
  const gap=parseFloat(getComputedStyle(s.track).gap)||0;
  s.loop=[...s.track.children].slice(0,s.count).reduce((sum,c)=>sum+c.getBoundingClientRect().width+gap,0);
  s.fits=s.count<2||s.loop-gap<=s.track.clientWidth;
  [...s.track.children].slice(s.count).forEach(c=>c.hidden=s.fits);
  s.controls.hidden=s.fits;
}
function block(place){
  let el=document.getElementById('promo-placement-'+place);if(el&&carousels.has(el))return el;if(el)el.remove();
  el=make('section',null,'promo-placement-block '+place);el.id='promo-placement-'+place;
  const header=make('header');header.append(make('span',place==='market'?'Featured · Sponsored':'Sponsored'));
  const link=make('a','View all →');link.href='/promote';header.append(link);
  const track=make('div',null,'promo-placement-grid promo-swipe-track');track.tabIndex=0;track.setAttribute('aria-label','Promoted tokens. Swipe left or right');
  const controls=make('div',null,'promo-strip-controls'),hint=make('span','Swipe ↔'),buttons=make('div');
  const previous=make('button','‹'),pause=make('button','Ⅱ'),next=make('button','›');
  previous.type=pause.type=next.type='button';previous.setAttribute('aria-label','Previous promotion');next.setAttribute('aria-label','Next promotion');pause.setAttribute('aria-label','Pause automatic promotions');pause.setAttribute('aria-pressed','false');
  buttons.append(previous,pause,next);controls.append(hint,buttons);el.append(header,track,controls);
  const s={track,controls,count:0,loop:0,visible:false,auto:true,down:false,hover:false,resumeAt:0,fits:true};carousels.set(el,s);carouselObserver.observe(el);
  scope.addEventListener(track,'pointerdown',()=>{s.down=true;pauseFor(s);},{passive:true});
  scope.addEventListener(window,'pointerup',()=>{s.down=false;pauseFor(s);},{passive:true});
  scope.addEventListener(window,'pointercancel',()=>{s.down=false;pauseFor(s);},{passive:true});
  scope.addEventListener(track,'wheel',()=>pauseFor(s),{passive:true});
  scope.addEventListener(el,'mouseenter',()=>{if(matchMedia('(hover:hover)').matches)s.hover=true;});
  scope.addEventListener(el,'mouseleave',()=>{s.hover=false;pauseFor(s);});
  function step(direction){pauseFor(s);const card=track.firstElementChild;if(!card)return;track.scrollBy({left:direction*(card.getBoundingClientRect().width+10),behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'auto':'smooth'});}
  scope.addEventListener(previous,'click',()=>step(-1));scope.addEventListener(next,'click',()=>step(1));
  scope.addEventListener(pause,'click',()=>{s.auto=!s.auto;pause.textContent=s.auto?'Ⅱ':'▶';pause.setAttribute('aria-pressed',String(!s.auto));pause.setAttribute('aria-label',s.auto?'Pause automatic promotions':'Resume automatic promotions');pauseFor(s);});
  scope.addEventListener(track,'keydown',e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();step(e.key==='ArrowLeft'?-1:1);}});
  return el;
}
function reset(el,rows){
  const s=carousels.get(el),signature=JSON.stringify(rows);if(s.signature===signature)return;
  s.signature=signature;
  el.querySelectorAll('.promo-ad').forEach(e=>{observer.unobserve(e);clearTimeout(timers.get(e));timers.delete(e);});
  const position=s.loop?s.track.scrollLeft/s.loop:0;
  const cards=rows.map(ad),duplicates=rows.length>1?rows.map(p=>{const c=ad(p);c.classList.add('promo-loop-copy');c.setAttribute('aria-hidden','true');c.querySelectorAll('a').forEach(a=>a.tabIndex=-1);return c;}):[];
  s.track.replaceChildren(...cards,...duplicates);s.count=rows.length;el.hidden=!rows.length;
  scope.requestAnimationFrame(()=>{sizeCarousel(s);s.track.scrollLeft=s.loop*position;});
}
let lastFrame=0;
function animateCarousel(now){
  const dt=Math.min(40,now-(lastFrame||now));lastFrame=now;
  if(!closed&&!document.hidden&&!matchMedia('(prefers-reduced-motion:reduce)').matches){
    carousels.forEach((s,el)=>{
      if(!el.isConnected||!s.visible||s.fits||!s.auto||s.down||s.hover||now<s.resumeAt||el.querySelector(':focus-visible')){s.position=s.track.scrollLeft;return;}
      if(s.position==null||Math.abs(s.track.scrollLeft-(s.lastSent||0))>2)s.position=s.track.scrollLeft;
      s.position+=dt*.018;
      if(s.position>=s.loop)s.position-=s.loop;
      s.track.scrollLeft=s.position;s.lastSent=s.track.scrollLeft;
    });
  }
  if(!closed)scope.requestAnimationFrame(animateCarousel);
}
scope.requestAnimationFrame(animateCarousel);
scope.addEventListener(window,'resize',()=>carousels.forEach(sizeCarousel));
function mountFeed(){const feed=document.getElementById('center-feed');if(!feed||!feedAd)return;const posts=[...feed.children].filter(e=>e.classList.contains('fc-card')||e.classList.contains('fc-repost-wrap'));if(!posts.length)return;const target=posts[Math.min(7,posts.length-1)];if(feedAd.parentNode!==feed||target.nextElementSibling!==feedAd){target.after(feedAd);scope.requestAnimationFrame(()=>sizeCarousel(carousels.get(feedAd)));feedAd.querySelectorAll('.promo-ad').forEach(e=>{if(!e.dataset.viewed)observer.observe(e);});}}
async function refresh(){if(document.hidden||closed||pending)return;const home=location.pathname==='/',market=location.pathname==='/live-market';if(!home&&!market)return;pending=true;try{for(const place of (home?['feed','banner']:['market'])){if(closed)break;let host;if(place==='market')host=document.querySelector('.pt-center');else host=document.getElementById('center-feed');if(!host)continue;const r=await request('/api/promote/featured?placement='+place,{credentials:'same-origin'}),d=await r.json();if(!d.ok||closed)continue;const el=block(place);reset(el,d.promotions);if(place==='feed'){feedAd=el;mountFeed();}else if(place==='banner'){host.before(el);}else{const title=host.querySelector('.pt-feed-hd');if(title)title.after(el);else host.prepend(el);}}}catch(e){if(e.name!=='AbortError')console.debug('Promotion placements unavailable');}finally{pending=false;}}
const mo=scope.mutationObserver(mountFeed);const feed=document.getElementById('center-feed');if(feed)mo.observe(feed,{childList:true});
const interval=scope.setInterval(refresh,60000);
function clearVisibleTimers(){timers.forEach(h=>clearTimeout(h));timers.clear();}
function stop(){closed=true;clearVisibleTimers();observer.disconnect();carouselObserver.disconnect();carousels.clear();mo.disconnect();scope.clearInterval(interval);scope?.cleanup('pagehide');}
if(scope){scope.onCleanup(()=>{closed=true;clearVisibleTimers();});scope.addEventListener(document,'visibilitychange',()=>{if(document.hidden)clearVisibleTimers();else refresh();});scope.addEventListener(window,'pagehide',stop);}else{window.addEventListener('pagehide',stop,{once:true});document.addEventListener('visibilitychange',()=>{if(document.hidden)clearVisibleTimers();else refresh();});}
refresh();
}
window.addEventListener('pageshow',e=>{if(e.persisted){window._orcPromotionPlacements=false;boot();}});
boot();
})();
