/* Shared OrcAgent top navbar controller. Pairs with the markup rendered by dashboard.py. */
(function(){
'use strict';

(function(){
  if(location.pathname.replace(/\/+$/,'')!=='/wallet') return;
  document.documentElement.classList.add('oa-pf-boot');
  var boot=document.createElement('style');boot.id='oa-pf-boot-style';boot.textContent='html.oa-pf-boot,html.oa-pf-boot body{background:#080d12!important}html.oa-pf-boot body{visibility:hidden!important}';document.head.appendChild(boot);
  var css=document.createElement('link');css.rel='stylesheet';css.href='/static/portfolio-redesign.css?v=4';document.head.appendChild(css);
  var js=document.createElement('script');js.src='/static/portfolio-redesign.js?v=4';js.defer=true;document.head.appendChild(js);
  var assets=document.createElement('script');assets.src='/static/portfolio-assets.js?v=1';assets.defer=true;document.head.appendChild(assets);
})();

(function(){
  var here=location.pathname.replace(/\/+$/,'')||'/';
  if(here!=='/'||!window.matchMedia('(min-width:1025px)').matches)return;
  var css=document.createElement('link');css.rel='stylesheet';css.href='/static/home-desktop.css?v=1';document.head.appendChild(css);
  var js=document.createElement('script');js.src='/static/home-desktop.js?v=1';js.defer=true;document.head.appendChild(js);
})();

(function(){
  var here=location.pathname.replace(/\/+$/,'')||'/';
  if(here!=='/'||!window.matchMedia('(max-width:767px)').matches)return;
  var css=document.createElement('link');css.rel='stylesheet';css.href='/static/home-mobile.css?v=4';document.head.appendChild(css);
  var guard=document.createElement('script');guard.src='/static/mobile-overscroll-guard.js?v=1';guard.defer=true;document.head.appendChild(guard);
  var js=document.createElement('script');js.src='/static/home-mobile.js?v=3';js.defer=true;document.head.appendChild(js);
})();

(function(){
  var here=location.pathname.replace(/\/+$/,'')||'/';
  if(here!=='/live-market')return;
  var css=document.createElement('link');css.rel='stylesheet';css.href='/static/live-market-redesign.css?v=7';document.head.appendChild(css);
  var js=document.createElement('script');js.src='/static/live-market-redesign.js?v=3';js.defer=true;document.head.appendChild(js);
})();

(function(){
  var here=location.pathname.replace(/\/+$/,'')||'/';
  if(here!=='/groups')return;
  var css=document.createElement('link');css.rel='stylesheet';css.href='/static/groups-redesign.css?v=1';document.head.appendChild(css);
  var js=document.createElement('script');js.src='/static/groups-redesign.js?v=1';js.defer=true;document.head.appendChild(js);
})();

/* Shared premium mobile bottom nav across OrcAgent. */
(function(){
  if(!window.matchMedia('(max-width:767px)').matches)return;
  var css=document.createElement('link');css.rel='stylesheet';css.href='/static/mobile-bottom-nav.css?v=3';document.head.appendChild(css);
  var js=document.createElement('script');js.src='/static/mobile-bottom-nav.js?v=4';js.defer=true;document.head.appendChild(js);
})();

/* Consistent reply/repost/like/bookmark SVGs wherever feed actions exist. */
(function(){
  var css=document.createElement('link');css.rel='stylesheet';css.href='/static/feed-action-icons.css?v=2';document.head.appendChild(css);
  var js=document.createElement('script');js.src='/static/feed-action-icons.js?v=1';js.defer=true;document.head.appendChild(js);
})();

var _NB_LIVE_CHAINS=['solana','bsc','base','arbitrum','polygon','robinhood'];
var _NB_CHAIN_LABELS={solana:'SOL',bsc:'BSC',base:'BASE',arbitrum:'ARB',polygon:'POLY',robinhood:'HOOD'};

(function(){
  var DEFAULT_FETCH_TIMEOUT_MS=15000,UPLOAD_FETCH_TIMEOUT_MS=60000,_origFetch=window.fetch.bind(window);
  window.fetch=function(input,init){if(init&&init.signal)return _origFetch(input,init);var isUpload=!!(init&&typeof FormData!=='undefined'&&init.body instanceof FormData),ctl=new AbortController(),timer=setTimeout(function(){ctl.abort()},isUpload?UPLOAD_FETCH_TIMEOUT_MS:DEFAULT_FETCH_TIMEOUT_MS),opts=Object.assign({},init||{},{signal:ctl.signal});return _origFetch(input,opts).finally(function(){clearTimeout(timer)})};
})();

(function(){
  var _hiddenAt=null;
  function _forceRepaint(){var el=document.documentElement,prev=el.style.opacity;el.style.opacity='0.99999';requestAnimationFrame(function(){el.style.opacity=prev})}
  document.addEventListener('visibilitychange',function(){if(document.hidden){_hiddenAt=Date.now();return}if(_hiddenAt&&Date.now()-_hiddenAt>3000)_forceRepaint();_hiddenAt=null});
  window.addEventListener('pageshow',function(e){if(e.persisted)_forceRepaint()});
})();

function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#39;'}[c]})}
function fmtPrice(n){n=Number(n);if(n==null||isNaN(n))return'—';if(n===0)return'$0.00';if(n>=1)return'$'+n.toFixed(2);if(n>=.01)return'$'+n.toFixed(4);if(n>=.0001)return'$'+n.toFixed(6);return'$'+n.toFixed(8)}
function logoTile(imgUrl,label,cls,phCls){var initials=esc((label||'?').slice(0,2).toUpperCase());if(!imgUrl)return'<div class="'+phCls+'">'+initials+'</div>';return'<img class="'+cls+'" src="'+esc(imgUrl)+'" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'">'+'<div class="'+phCls+'" style="display:none">'+initials+'</div>'}
function closeAllOverlays(){var nav=document.getElementById('pt-nb-nav'),more=document.getElementById('pt-nb-more-dd'),scrim=document.getElementById('pt-nb-scrim'),results=document.getElementById('pt-nb-search-results');if(nav)nav.classList.remove('mobile-open');if(more)more.classList.remove('open');if(scrim)scrim.classList.remove('show');if(results)results.classList.remove('open')}
function markCurrentNavItem(){var here=location.pathname.replace(/\/+$/,'')||'/';document.querySelectorAll('.pt-nb-more-item[href]').forEach(function(a){var href=(a.getAttribute('href')||'').replace(/\/+$/,'')||'/';a.classList.toggle('current',href===here)})}

document.addEventListener('DOMContentLoaded',function(){
  var root=document.querySelector('.pt-nb-topbar');if(!root)return;markCurrentNavItem();
  if(location.pathname.replace(/\/+$/,'')==='/wallet')document.querySelectorAll('a[href="/wallet"],a[href^="/wallet?"]').forEach(function(a){if(/wallet/i.test(a.textContent||''))a.textContent=(a.textContent||'').replace(/wallet/ig,'Portfolio')});
  var menuBtn=document.getElementById('pt-nb-menu-btn'),navEl=document.getElementById('pt-nb-nav'),moreBtn=document.getElementById('pt-nb-more-btn'),moreDd=document.getElementById('pt-nb-more-dd'),scrimEl=document.getElementById('pt-nb-scrim'),searchIn=document.getElementById('pt-nb-search-input'),searchRes=document.getElementById('pt-nb-search-results'),searchWrap=searchIn&&searchIn.closest('.pt-nb-search-wrap'),searchClose=document.getElementById('pt-nb-search-close');
  if(searchIn){searchIn.type='search';searchIn.setAttribute('inputmode','search');searchIn.setAttribute('aria-label','Search tokens and traders')}
  if(searchWrap&&!searchClose){searchClose=document.createElement('button');searchClose.id='pt-nb-search-close';searchClose.className='pt-nb-search-close';searchClose.type='button';searchClose.setAttribute('aria-label','Close search');searchClose.innerHTML='&times;';searchWrap.insertBefore(searchClose,searchRes||null)}
  if(menuBtn)menuBtn.addEventListener('click',function(e){e.stopPropagation();var opening=navEl&&!navEl.classList.contains('mobile-open');closeAllOverlays();if(opening&&navEl){navEl.classList.add('mobile-open');if(scrimEl)scrimEl.classList.add('show')}});
  if(moreBtn)moreBtn.addEventListener('click',function(e){e.stopPropagation();var opening=moreDd&&!moreDd.classList.contains('open');closeAllOverlays();if(opening&&moreDd)moreDd.classList.add('open')});
  if(scrimEl)scrimEl.addEventListener('click',closeAllOverlays);
  document.querySelectorAll('.pt-nb-disconnect-btn').forEach(function(disconnectBtn){disconnectBtn.addEventListener('click',function(){if(typeof window.disconnectWallet==='function'){window.disconnectWallet();return}fetch('/api/logout',{method:'POST',credentials:'include'}).catch(function(){}).finally(function(){window.location.href='/'})})});
  document.addEventListener('click',function(e){if(moreDd&&moreDd.classList.contains('open')&&!e.target.closest('.pt-nb-more-wrap'))moreDd.classList.remove('open');if(searchRes&&searchRes.classList.contains('open')&&!e.target.closest('.pt-nb-search-wrap'))searchRes.classList.remove('open')});
  var _searchTimer=null,_searchSeq=0;
  function openMobileSearch(){if(!searchWrap||!window.matchMedia('(max-width:767px)').matches)return;searchWrap.classList.add('mobile-search-open');document.body.classList.add('oa-search-open');setTimeout(function(){searchIn.focus()},0)}
  function closeMobileSearch(){if(!searchWrap)return;searchWrap.classList.remove('mobile-search-open');document.body.classList.remove('oa-search-open');if(searchRes)searchRes.classList.remove('open');searchIn.blur()}
  if(searchIn){searchIn.addEventListener('focus',openMobileSearch);searchIn.addEventListener('click',openMobileSearch);searchIn.addEventListener('input',function(){var q=searchIn.value.trim();clearTimeout(_searchTimer);if(q.length<2){if(searchRes){searchRes.innerHTML='<div class="pt-nb-sr-empty">Type at least 2 characters</div>';searchRes.classList.toggle('open',!!q)}return}if(searchRes){searchRes.innerHTML='<div class="pt-nb-sr-empty">Searching…</div>';searchRes.classList.add('open')}_searchTimer=setTimeout(function(){runSearch(q)},250)})}
  if(searchClose)searchClose.addEventListener('click',closeMobileSearch);
  document.addEventListener('keydown',function(e){if(e.key==='Escape')closeMobileSearch()});
  function runSearch(q){var seq=++_searchSeq;Promise.allSettled([fetch('/api/dexscreener/search?q='+encodeURIComponent(q)).then(function(r){if(!r.ok)throw new Error('token search');return r.json()}),fetch('/api/users/search?q='+encodeURIComponent(q),{credentials:'include'}).then(function(r){if(!r.ok)throw new Error('user search');return r.json()})]).then(function(results){if(seq!==_searchSeq||searchIn.value.trim()!==q)return;var tokRes=results[0].status==='fulfilled'?results[0].value:null,userRes=results[1].status==='fulfilled'?results[1].value:null,pairs=((tokRes&&tokRes.pairs)||[]).filter(function(p){return p&&p.baseToken&&_NB_LIVE_CHAINS.indexOf(p.chainId)!==-1}).slice(0,6),users=(userRes&&userRes.ok&&userRes.users)||[],html='';if(pairs.length)html+='<div class="pt-nb-sr-hd">Tokens</div>'+pairs.map(function(p){var sym=p.baseToken.symbol||'TOKEN',addr=p.baseToken.address||'',img=p.info&&p.info.imageUrl,chainLbl=_NB_CHAIN_LABELS[p.chainId]||p.chainId;return'<div class="pt-nb-sr-row" data-action="tok" data-mint="'+esc(addr)+'" data-chain="'+esc(p.chainId)+'">'+logoTile(img,sym,'pt-nb-sr-logo','pt-nb-sr-logo-ph')+'<div class="pt-nb-sr-name">$'+esc(sym)+' <span class="pt-nb-sr-chain">'+esc(chainLbl)+'</span></div><div class="pt-nb-sr-sub">'+fmtPrice(p.priceUsd)+'</div></div>'}).join('');if(users.length)html+='<div class="pt-nb-sr-hd">Traders</div>'+users.slice(0,5).map(function(u){return'<div class="pt-nb-sr-row" data-action="trader" data-wallet="'+esc(u.wallet)+'">'+logoTile(u.avatar_url,u.username,'pt-nb-sr-logo','pt-nb-sr-logo-ph')+'<div class="pt-nb-sr-name">'+esc(u.username||'Unknown trader')+'</div></div>'}).join('');if(searchRes){searchRes.innerHTML=html||'<div class="pt-nb-sr-empty">No tokens or traders found</div>';searchRes.classList.add('open')}})}
  if(searchRes)searchRes.addEventListener('click',function(e){var tok=e.target.closest('[data-action="tok"]');if(tok){window.location.href='/live-market?mint='+encodeURIComponent(tok.dataset.mint);return}var trader=e.target.closest('[data-action="trader"]');if(trader)window.location.href='/profile/'+encodeURIComponent(trader.dataset.wallet)});
  fetch('/api/me',{credentials:'include'}).then(function(r){return r.json()}).then(function(d){if(!d||!d.ok)return;var balEl=document.getElementById('pt-nb-sol-balance');if(balEl)balEl.textContent=Number(d.balance||0).toFixed(2);if(d.avatar){var img=document.getElementById('pt-nb-avatar'),ph=document.getElementById('pt-nb-avatar-ph');if(img){img.src=d.avatar;img.style.display='block'}if(ph)ph.style.display='none'}if(d.is_admin)document.querySelectorAll('.pt-nb-admin-link').forEach(function(x){x.style.display='flex'})}).catch(function(){});
  function refreshBadges(){fetch('/api/messages/unread_count',{credentials:'include'}).then(function(r){return r.json()}).then(function(d){var n=(d&&d.count)||0;['pt-nb-msg-badge','pt-nb-more-msg-badge'].forEach(function(id){var el=document.getElementById(id);if(!el)return;el.textContent=n>99?'99+':String(n);el.classList.toggle('show',n>0)})}).catch(function(){});fetch('/api/notifications/mine/unread_count',{credentials:'include'}).then(function(r){return r.json()}).then(function(d){var n=(d&&d.ok&&d.unread)||0;['pt-nb-notif-badge','pt-nb-more-notif-badge'].forEach(function(id){var el=document.getElementById(id);if(!el)return;el.textContent=n>99?'99+':String(n);el.classList.toggle('show',n>0)})}).catch(function(){})}
  refreshBadges();setInterval(refreshBadges,30000);
});
})();