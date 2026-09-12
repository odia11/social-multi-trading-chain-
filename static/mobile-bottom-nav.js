/* Shared OrcAgent mobile bottom navigation */
(function(){
'use strict';
if(!window.matchMedia('(max-width:767px)').matches)return;
function icon(name){var d={
home:'<path d="m3 10 9-7 9 7"/><path d="M5 9v11h14V9"/><path d="M9 20v-6h6v6"/>',
market:'<path d="M4 19V11"/><path d="M10 19V6"/><path d="M16 19V9"/><path d="M22 19V3"/>',
post:'<path d="M12 5v14"/><path d="M5 12h14"/>',
portfolio:'<rect x="3" y="6" width="18" height="14" rx="3"/><path d="M8 6V4h8v2"/><path d="M15 11h6v4h-6a2 2 0 0 1 0-4Z"/>',
walletAction:'<rect x="3" y="6" width="18" height="14" rx="3"/><path d="M16 11h5v4h-5a2 2 0 0 1 0-4Z"/><path d="M8 4h8"/><path d="m7 12 2-2 2 2M9 10v5"/>',
createGroup:'<circle cx="9" cy="8" r="3"/><path d="M3 20v-1a6 6 0 0 1 12 0v1"/><path d="M19 8v6M16 11h6"/>',
menu:'<path d="M4 6h16M4 12h16M4 18h16"/>',
deposit:'<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
withdraw:'<path d="M12 21V9"/><path d="m7 14 5-5 5 5"/><path d="M5 3h14"/>',
swap:'<path d="M4 7h15"/><path d="m16 4 3 3-3 3"/><path d="M20 17H5"/><path d="m8 14-3 3 3 3"/>',
bridge:'<path d="M4 17c2-6 5-9 8-9s6 3 8 9"/><path d="M4 17h16"/><path d="M7 17v4M17 17v4"/>'};return '<svg viewBox="0 0 24 24" aria-hidden="true">'+d[name]+'</svg>'}
function here(){return location.pathname.replace(/\/+$/,'')||'/'}
function normPath(href){try{return new URL(href,location.href).pathname.replace(/\/+$/,'')||'/'}catch(e){return href||''}}
function closeWalletSheet(){var s=document.getElementById('oa-wallet-actions');if(s)s.classList.remove('open');document.documentElement.classList.remove('oa-wallet-actions-open')}
function findBridgeTrigger(){var el=document.querySelector('[data-action="bridge"],#bridge-btn,.bridge-btn,[data-bridge]');if(el)return el;var all=document.querySelectorAll('button,a');for(var i=0;i<all.length;i++){if(/^\s*bridge\b/i.test(all[i].textContent||''))return all[i]}return null}
function runWalletAction(action){closeWalletSheet();if(action==='deposit'){var d=document.getElementById('pf-deposit');if(d){d.click();return}}if(action==='withdraw'){var w=document.getElementById('pf-withdraw');if(w){w.click();return}if(typeof window._modalSend==='function'){window._modalSend();return}}if(action==='swap'){var b=document.querySelector('.tok-trade-btn');if(b){b.click();return}if(typeof window.openSwapModal==='function'){window.openSwapModal('So11111111111111111111111111111111111111112');return}location.href='/live-market';return}if(action==='bridge'){var bt=findBridgeTrigger();if(bt){bt.click();return}}}
function buildWalletSheet(){if(here()!=='/wallet'||document.getElementById('oa-wallet-actions'))return;var bridge=!!findBridgeTrigger();var wrap=document.createElement('div');wrap.id='oa-wallet-actions';wrap.className='oa-wallet-actions';wrap.innerHTML='<button class="oa-wallet-scrim" aria-label="Close wallet actions"></button><section class="oa-wallet-sheet" role="dialog" aria-modal="true" aria-label="Portfolio actions"><div class="oa-wallet-grab"></div><div class="oa-wallet-sheet-head"><div><strong>Portfolio actions</strong><span>What do you want to do?</span></div><button type="button" class="oa-wallet-close" aria-label="Close">×</button></div><div class="oa-wallet-action-grid"><button type="button" data-wallet-action="deposit">'+icon('deposit')+'<strong>Deposit</strong><span>Add funds</span></button><button type="button" data-wallet-action="withdraw">'+icon('withdraw')+'<strong>Withdraw</strong><span>Send funds</span></button><button type="button" data-wallet-action="swap">'+icon('swap')+'<strong>Swap</strong><span>Exchange assets</span></button>'+(bridge?'<button type="button" data-wallet-action="bridge">'+icon('bridge')+'<strong>Bridge</strong><span>Cross-chain</span></button>':'')+'</div></section>';document.body.appendChild(wrap);wrap.addEventListener('click',function(e){if(e.target.closest('.oa-wallet-scrim,.oa-wallet-close')){closeWalletSheet();return}var a=e.target.closest('[data-wallet-action]');if(a)runWalletAction(a.dataset.walletAction)})}
function openWalletSheet(){buildWalletSheet();var s=document.getElementById('oa-wallet-actions');if(!s)return;s.classList.add('open');document.documentElement.classList.add('oa-wallet-actions-open')}
function openCreateGroup(){if(typeof window._openCreateGroupModal==='function'){window._openCreateGroupModal();return}var b=Array.prototype.slice.call(document.querySelectorAll('button')).find(function(x){return /create\s+group/i.test(x.textContent||'')});if(b)b.click()}

function focusSocialComposer(attempt){
  attempt=attempt||0;
  var composer=document.getElementById('feed-composer'),input=document.getElementById('postText');
  if(!composer||!input){if(attempt<12)setTimeout(function(){focusSocialComposer(attempt+1)},80);return}
  composer.classList.add('expanded');
  try{composer.scrollIntoView({behavior:'smooth',block:'center'})}catch(e){composer.scrollIntoView()}
  setTimeout(function(){try{input.focus({preventScroll:true})}catch(e){input.focus()}},260);
  try{
    var u=new URL(location.href);
    if(u.searchParams.get('compose')==='1'){
      u.searchParams.delete('compose');
      var qs=u.searchParams.toString();
      history.replaceState(history.state,'',u.pathname+(qs?'?'+qs:'')+(u.hash||''));
    }
  }catch(e){}
}
function openSocialComposer(){
  closeAppMenu();closeWalletSheet();
  if(here()!=='/'){
    location.href='/?compose=1#feed-composer';
    return;
  }
  focusSocialComposer(0);
}
function centerHtml(p){return '<button type="button" class="oa-trade-main oa-post-main'+(p==='/'?' active':'')+'" aria-label="Create post">'+icon('post')+'<span>POST</span></button>'}

function closeAppMenu(){var m=document.getElementById('oa-app-menu');if(m)m.classList.remove('open');document.documentElement.classList.remove('oa-app-menu-open');var b=document.querySelector('.oa-bottom-nav .oa-menu-btn');if(b)b.classList.remove('active')}
function buildAppMenu(){var old=document.getElementById('oa-app-menu');if(old)return old;var source=document.getElementById('pt-nb-nav'),wrap=document.createElement('div');wrap.id='oa-app-menu';wrap.className='oa-app-menu';wrap.innerHTML='<button class="oa-app-menu-scrim" aria-label="Close menu"></button><section class="oa-app-menu-sheet" role="dialog" aria-modal="true" aria-label="OrcAgent menu"><div class="oa-app-menu-grab"></div><div class="oa-app-menu-head"><strong>Menu</strong><button type="button" class="oa-app-menu-close" aria-label="Close">×</button></div><div class="oa-app-menu-grid"></div></section>';var grid=wrap.querySelector('.oa-app-menu-grid'),seen={};if(source){Array.prototype.forEach.call(source.querySelectorAll('a[href],button.pt-nb-more-item'),function(src){var isLink=src.tagName==='A',href=isLink?(src.getAttribute('href')||''):'',p=isLink?normPath(href):'',text=(src.textContent||'').trim();if(isLink&&(p==='/'||p==='/live-market'||p==='/wallet'))return;if(!text)return;var key=isLink?p:'btn:'+text.toLowerCase();if(seen[key])return;seen[key]=1;if(src.classList.contains('pt-nb-nav-sep')||src.classList.contains('pt-nb-more-sep'))return;var item=document.createElement(isLink?'a':'button');if(isLink)item.href=href;else item.type='button';item.className='oa-app-menu-item'+(src.classList.contains('danger')?' danger':'')+(isLink&&p===here()?' current':'');var svg=src.querySelector('svg');if(svg)item.appendChild(svg.cloneNode(true));var label=document.createElement('span');label.textContent=text.replace(/\d+$/,'').trim();item.appendChild(label);if(!isLink)item.addEventListener('click',function(){closeAppMenu();src.click()});grid.appendChild(item)})}document.body.appendChild(wrap);wrap.addEventListener('click',function(e){if(e.target.closest('.oa-app-menu-scrim,.oa-app-menu-close'))closeAppMenu()});return wrap}
function openAppMenu(){var m=buildAppMenu();m.classList.add('open');document.documentElement.classList.add('oa-app-menu-open');var b=document.querySelector('.oa-bottom-nav .oa-menu-btn');if(b)b.classList.add('active')}

function ensureHomeComposerStyles(){
  if(here()!=='/'||document.getElementById('oa-home-composer-mobile-css'))return;
  var css=document.createElement('link');css.id='oa-home-composer-mobile-css';css.rel='stylesheet';css.href='/static/home-composer-mobile.css?v=1';document.head.appendChild(css);
}
function build(){if(document.getElementById('oa-bottom-nav'))return;ensureHomeComposerStyles();var nav=document.createElement('nav');nav.id='oa-bottom-nav';nav.className='oa-bottom-nav';nav.setAttribute('aria-label','Mobile navigation');var p=here(),wallet=p==='/wallet';nav.innerHTML='<a href="/" class="'+(p==='/'?'active':'')+'">'+icon('home')+'<span class="oa-nav-label">Home</span></a>'+
'<a href="/live-market" class="'+(p==='/live-market'?'active':'')+'">'+icon('market')+'<span class="oa-nav-label">Live Market</span></a>'+centerHtml(p)+
'<a href="/wallet" class="'+(wallet?'active':'')+'">'+icon('portfolio')+'<span class="oa-nav-label">Portfolio</span></a>'+
'<button type="button" class="oa-menu-btn" aria-label="Open menu">'+icon('menu')+'<span class="oa-nav-label">Menu</span></button>';
document.body.appendChild(nav);var btn=nav.querySelector('.oa-menu-btn');if(btn)btn.addEventListener('click',openAppMenu);var postBtn=nav.querySelector('.oa-post-main');if(postBtn)postBtn.addEventListener('click',openSocialComposer);buildWalletSheet();buildAppMenu();
if(p==='/'&&((new URLSearchParams(location.search)).get('compose')==='1'||location.hash==='#feed-composer'))requestAnimationFrame(function(){requestAnimationFrame(function(){focusSocialComposer(0)})})
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',build,{once:true});else build();
})();
