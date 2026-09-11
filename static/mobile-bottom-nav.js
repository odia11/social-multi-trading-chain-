/* Shared OrcAgent mobile bottom navigation */
(function(){
'use strict';
if(!window.matchMedia('(max-width:767px)').matches)return;
function icon(name){var d={home:'<path d="m3 10 9-7 9 7"/><path d="M5 9v11h14V9"/><path d="M9 20v-6h6v6"/>',market:'<path d="M4 19V11"/><path d="M10 19V6"/><path d="M16 19V9"/><path d="M22 19V3"/>',trade:'<path d="M5 7h13"/><path d="m15 4 3 3-3 3"/><path d="M19 17H6"/><path d="m9 14-3 3 3 3"/>',portfolio:'<rect x="3" y="6" width="18" height="14" rx="3"/><path d="M8 6V4h8v2"/><path d="M15 11h6v4h-6a2 2 0 0 1 0-4Z"/>',menu:'<path d="M4 6h16M4 12h16M4 18h16"/>'};return '<svg viewBox="0 0 24 24" aria-hidden="true">'+d[name]+'</svg>'}
function here(){return location.pathname.replace(/\/+$/,'')||'/'}
function build(){if(document.getElementById('oa-bottom-nav'))return;var nav=document.createElement('nav');nav.id='oa-bottom-nav';nav.className='oa-bottom-nav';nav.setAttribute('aria-label','Mobile navigation');var p=here();nav.innerHTML='<a href="/" class="'+(p==='/'?'active':'')+'">'+icon('home')+'<span class="oa-nav-label">Home</span></a>'+
'<a href="/live-market" class="'+(p==='/live-market'?'active':'')+'">'+icon('market')+'<span class="oa-nav-label">Live Market</span></a>'+
'<a href="/live-market" class="oa-trade-main '+(p==='/live-market'?'active':'')+'" aria-label="Trade">'+icon('trade')+'<span>Trade</span></a>'+
'<a href="/wallet" class="'+(p==='/wallet'?'active':'')+'">'+icon('portfolio')+'<span class="oa-nav-label">Portfolio</span></a>'+
'<button type="button" class="oa-menu-btn" aria-label="Open menu">'+icon('menu')+'<span class="oa-nav-label">Menu</span></button>';
document.body.appendChild(nav);var btn=nav.querySelector('.oa-menu-btn');if(btn)btn.addEventListener('click',function(){var existing=document.getElementById('pt-nb-menu-btn');if(existing){existing.click();return}var more=document.getElementById('pt-nb-more-btn');if(more)more.click()});}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',build);else build();
})();
