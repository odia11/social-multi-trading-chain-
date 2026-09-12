/* Shared OrcAgent mobile bottom navigation */
(function(){
'use strict';
if(!window.matchMedia('(max-width:767px)').matches)return;
function icon(name){var d={
home:'<path d="m3 10 9-7 9 7"/><path d="M5 9v11h14V9"/><path d="M9 20v-6h6v6"/>',
market:'<path d="M4 19V11"/><path d="M10 19V6"/><path d="M16 19V9"/><path d="M22 19V3"/>',
post:'<path d="M22 2 11 13"/><path d="m22 2-7 20-4-9-9-4Z"/>',
portfolio:'<rect x="3" y="6" width="18" height="14" rx="3"/><path d="M8 6V4h8v2"/><path d="M15 11h6v4h-6a2 2 0 0 1 0-4Z"/>',
menu:'<path d="M4 6h16M4 12h16M4 18h16"/>'};return '<svg viewBox="0 0 24 24" aria-hidden="true">'+d[name]+'</svg>'}
function here(){return location.pathname.replace(/\/+$/,'')||'/'}
function normPath(href){try{return new URL(href,location.href).pathname.replace(/\/+$/,'')||'/'}catch(e){return href||''}}
function openPostComposer(){
  if(here()!=='/'){
    location.href='/?compose=1#feed-composer';
    return;
  }
  var c=document.getElementById('feed-composer'),t=document.getElementById('postText');
  if(!c||!t){location.href='/?compose=1#feed-composer';return}
  c.classList.add('expanded','oa-post-open');
  try{c.scrollIntoView({behavior:'smooth',block:'start'})}catch(e){c.scrollIntoView(true)}
  setTimeout(function(){t.focus();try{t.setSelectionRange(t.value.length,t.value.length)}catch(_){ }},180);
  try{history.replaceState(null,'',location.pathname)}catch(_){ }
}
function closeAppMenu(){var m=document.getElementById('oa-app-menu');if(m)m.classList.remove('open');document.documentElement.classList.remove('oa-app-menu-open');var b=document.querySelector('.oa-bottom-nav .oa-menu-btn');if(b)b.classList.remove('active')}
function buildAppMenu(){var old=document.getElementById('oa-app-menu');if(old)return old;var source=document.getElementById('pt-nb-nav'),wrap=document.createElement('div');wrap.id='oa-app-menu';wrap.className='oa-app-menu';wrap.innerHTML='<button class="oa-app-menu-scrim" aria-label="Close menu"></button><section class="oa-app-menu-sheet" role="dialog" aria-modal="true" aria-label="OrcAgent menu"><div class="oa-app-menu-grab"></div><div class="oa-app-menu-head"><strong>Menu</strong><button type="button" class="oa-app-menu-close" aria-label="Close">×</button></div><div class="oa-app-menu-grid"></div></section>';var grid=wrap.querySelector('.oa-app-menu-grid'),seen={};if(source){Array.prototype.forEach.call(source.querySelectorAll('a[href],button.pt-nb-more-item'),function(src){var isLink=src.tagName==='A',href=isLink?(src.getAttribute('href')||''):'',p=isLink?normPath(href):'',text=(src.textContent||'').trim();if(isLink&&(p==='/'||p==='/live-market'||p==='/wallet'))return;if(!text)return;var key=isLink?p:'btn:'+text.toLowerCase();if(seen[key])return;seen[key]=1;if(src.classList.contains('pt-nb-nav-sep')||src.classList.contains('pt-nb-more-sep'))return;var item=document.createElement(isLink?'a':'button');if(isLink)item.href=href;else item.type='button';item.className='oa-app-menu-item'+(src.classList.contains('danger')?' danger':'')+(isLink&&p===here()?' current':'');var svg=src.querySelector('svg');if(svg)item.appendChild(svg.cloneNode(true));var label=document.createElement('span');label.textContent=text.replace(/\d+$/,'').trim();item.appendChild(label);if(!isLink)item.addEventListener('click',function(){closeAppMenu();src.click()});grid.appendChild(item)})}document.body.appendChild(wrap);wrap.addEventListener('click',function(e){if(e.target.closest('.oa-app-menu-scrim,.oa-app-menu-close'))closeAppMenu()});return wrap}
function openAppMenu(){var m=buildAppMenu();m.classList.add('open');document.documentElement.classList.add('oa-app-menu-open');var b=document.querySelector('.oa-bottom-nav .oa-menu-btn');if(b)b.classList.add('active')}
function build(){
  if(document.getElementById('oa-bottom-nav'))return;
  var nav=document.createElement('nav');nav.id='oa-bottom-nav';nav.className='oa-bottom-nav';nav.setAttribute('aria-label','Mobile navigation');
  var p=here(),wallet=p==='/wallet';
  nav.innerHTML='<a href="/" class="'+(p==='/'?'active':'')+'">'+icon('home')+'<span class="oa-nav-label">Home</span></a>'+
    '<a href="/live-market" class="'+(p==='/live-market'?'active':'')+'">'+icon('market')+'<span class="oa-nav-label">Live Market</span></a>'+
    '<button type="button" class="oa-trade-main oa-post-main active" aria-label="Create post">'+icon('post')+'<span>Post</span></button>'+
    '<a href="/wallet" class="'+(wallet?'active':'')+'">'+icon('portfolio')+'<span class="oa-nav-label">Portfolio</span></a>'+
    '<button type="button" class="oa-menu-btn" aria-label="Open menu">'+icon('menu')+'<span class="oa-nav-label">Menu</span></button>';
  document.body.appendChild(nav);
  var post=nav.querySelector('.oa-post-main');if(post)post.addEventListener('click',openPostComposer);
  var menu=nav.querySelector('.oa-menu-btn');if(menu)menu.addEventListener('click',openAppMenu);
  buildAppMenu();
  addEventListener('oa:open-composer',openPostComposer);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',build);else build();
})();
