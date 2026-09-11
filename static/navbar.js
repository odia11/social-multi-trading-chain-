/* Shared OrcAgent top navbar controller. Pairs with the markup rendered by
   dashboard.py's _navbar_html() (used by every page via a Jinja global on
   render_template()-based pages, and spliced into dashboard.html's raw HTML
   the same way the modal partials are). Self-contained: does not assume any
   other script on the page has already run. */
(function(){
'use strict';

/* /wallet is now presented as Portfolio. Keep the URL stable so every old
   link, test and server route keeps working; load the presentation layer
   before DOMContentLoaded so it can enhance the existing, tested wallet UI. */
(function(){
  if(location.pathname.replace(/\/+$/,'')!=='/wallet') return;
  var css=document.createElement('link'); css.rel='stylesheet'; css.href='/static/portfolio-redesign.css?v=3'; document.head.appendChild(css);
  var js=document.createElement('script'); js.src='/static/portfolio-redesign.js?v=3'; js.defer=true; document.head.appendChild(js);
  var assets=document.createElement('script'); assets.src='/static/portfolio-assets.js?v=1'; assets.defer=true; document.head.appendChild(assets);
})();

/* Desktop home redesign: presentation-only layer for the dashboard root. */
(function(){
  var here=location.pathname.replace(/\/+$/,'')||'/';
  if(here!=='/' || !window.matchMedia('(min-width:1025px)').matches) return;
  var css=document.createElement('link'); css.rel='stylesheet'; css.href='/static/home-desktop.css?v=1'; document.head.appendChild(css);
  var js=document.createElement('script'); js.src='/static/home-desktop.js?v=1'; js.defer=true; document.head.appendChild(js);
})();

/* Mobile home redesign. It only changes presentation on the dashboard root;
   the existing composer/feed/mobile-nav stay responsible for the actions. */
(function(){
  var here=location.pathname.replace(/\/+$/,'')||'/';
  if(here!=='/' || !window.matchMedia('(max-width:767px)').matches) return;
  var css=document.createElement('link'); css.rel='stylesheet'; css.href='/static/home-mobile.css?v=1'; document.head.appendChild(css);
  var js=document.createElement('script'); js.src='/static/home-mobile.js?v=1'; js.defer=true; document.head.appendChild(js);
})();

var _NB_LIVE_CHAINS = ['solana', 'bsc', 'base', 'arbitrum', 'polygon', 'robinhood'];
var _NB_CHAIN_LABELS = {solana:'SOL', bsc:'BSC', base:'BASE', arbitrum:'ARB', polygon:'POLY', robinhood:'HOOD'};

(function(){
  var DEFAULT_FETCH_TIMEOUT_MS = 15000;
  var UPLOAD_FETCH_TIMEOUT_MS  = 60000;
  var _origFetch = window.fetch.bind(window);
  window.fetch = function(input, init){
    if(init && init.signal) return _origFetch(input, init);
    var isUpload = !!(init && typeof FormData !== 'undefined' && init.body instanceof FormData);
    var ctl = new AbortController();
    var timer = setTimeout(function(){ ctl.abort(); }, isUpload ? UPLOAD_FETCH_TIMEOUT_MS : DEFAULT_FETCH_TIMEOUT_MS);
    var opts = Object.assign({}, init || {}, {signal: ctl.signal});
    return _origFetch(input, opts).finally(function(){ clearTimeout(timer); });
  };
})();

(function(){
  var _hiddenAt = null;
  function _forceRepaint(){
    var el = document.documentElement;
    var prev = el.style.opacity;
    el.style.opacity = '0.99999';
    requestAnimationFrame(function(){ el.style.opacity = prev; });
  }
  document.addEventListener('visibilitychange', function(){
    if(document.hidden){ _hiddenAt = Date.now(); return; }
    if(_hiddenAt && Date.now() - _hiddenAt > 3000) _forceRepaint();
    _hiddenAt = null;
  });
  window.addEventListener('pageshow', function(e){ if(e.persisted) _forceRepaint(); });
})();

function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function fmtPrice(n){n=Number(n);if(n==null||isNaN(n))return '—';if(n===0)return '$0.00';if(n>=1)return '$'+n.toFixed(2);if(n>=.01)return '$'+n.toFixed(4);if(n>=.0001)return '$'+n.toFixed(6);return '$'+n.toFixed(8);}
function logoTile(imgUrl,label,cls,phCls){var initials=esc((label||'?').slice(0,2).toUpperCase());if(!imgUrl)return '<div class="'+phCls+'">'+initials+'</div>';return '<img class="'+cls+'" src="'+esc(imgUrl)+'" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'">'+'<div class="'+phCls+'" style="display:none">'+initials+'</div>';}
function closeAllOverlays(){var nav=document.getElementById('pt-nb-nav'),more=document.getElementById('pt-nb-more-dd'),scrim=document.getElementById('pt-nb-scrim'),results=document.getElementById('pt-nb-search-results');if(nav)nav.classList.remove('mobile-open');if(more)more.classList.remove('open');if(scrim)scrim.classList.remove('show');if(results)results.classList.remove('open');}
function markCurrentNavItem(){var here=location.pathname.replace(/\/+$/,'')||'/';document.querySelectorAll('.pt-nb-more-item[href]').forEach(function(a){var href=(a.getAttribute('href')||'').replace(/\/+$/,'')||'/';a.classList.toggle('current',href===here);});}

document.addEventListener('DOMContentLoaded',function(){
  var root=document.querySelector('.pt-nb-topbar');if(!root)return;markCurrentNavItem();
  /* Rename the product destination without changing the stable /wallet route. */
  if(location.pathname.replace(/\/+$/,'')==='/wallet') document.querySelectorAll('a[href="/wallet"],a[href^="/wallet?"]').forEach(function(a){if(/wallet/i.test(a.textContent||''))a.textContent=(a.textContent||'').replace(/wallet/ig,'Portfolio');});
  var menuBtn=document.getElementById('pt-nb-menu-btn'),navEl=document.getElementById('pt-nb-nav'),moreBtn=document.getElementById('pt-nb-more-btn'),moreDd=document.getElementById('pt-nb-more-dd'),scrimEl=document.getElementById('pt-nb-scrim'),searchIn=document.getElementById('pt-nb-search-input'),searchRes=document.getElementById('pt-nb-search-results');
  if(menuBtn)menuBtn.addEventListener('click',function(e){e.stopPropagation();var opening=!navEl.classList.contains('mobile-open');closeAllOverlays();if(opening){navEl.classList.add('mobile-open');if(scrimEl)scrimEl.classList.add('show');}});
  if(moreBtn)moreBtn.addEventListener('click',function(e){e.stopPropagation();var opening=!moreDd.classList.contains('open');closeAllOverlays();if(opening)moreDd.classList.add('open');});
  if(scrimEl)scrimEl.addEventListener('click',closeAllOverlays);
  document.querySelectorAll('.pt-nb-disconnect-btn').forEach(function(disconnectBtn){disconnectBtn.addEventListener('click',function(){if(typeof window.disconnectWallet==='function'){window.disconnectWallet();return;}fetch('/api/logout',{method:'POST',credentials:'include'}).catch(function(){}).finally(function(){window.location.href='/';});});});
  document.addEventListener('click',function(e){if(moreDd&&moreDd.classList.contains('open')&&!e.target.closest('.pt-nb-more-wrap'))moreDd.classList.remove('open');if(searchRes&&searchRes.classList.contains('open')&&!e.target.closest('.pt-nb-search-wrap'))searchRes.classList.remove('open');});
  var _searchTimer=null;
  if(searchIn)searchIn.addEventListener('input',function(){var q=searchIn.value.trim();clearTimeout(_searchTimer);if(q.length<2){searchRes.classList.remove('open');return;}_searchTimer=setTimeout(function(){runSearch(q);},300);});
  function runSearch(q){Promise.allSettled([fetch('/api/dexscreener/search?q='+encodeURIComponent(q)).then(function(r){return r.json();}),fetch('/api/users/search?q='+encodeURIComponent(q),{credentials:'include'}).then(function(r){return r.json();})]).then(function(results){var tokRes=results[0].status==='fulfilled'?results[0].value:null,userRes=results[1].status==='fulfilled'?results[1].value:null;var pairs=((tokRes&&tokRes.pairs)||[]).filter(function(p){return _NB_LIVE_CHAINS.indexOf(p.chainId)!==-1;}).slice(0,6),users=(userRes&&userRes.ok&&userRes.users)||[],html='';if(pairs.length)html+='<div class="pt-nb-sr-hd">Tokens</div>'+pairs.map(function(p){var sym=p.baseToken.symbol,addr=p.baseToken.address,img=p.info&&p.info.imageUrl,chainLbl=_NB_CHAIN_LABELS[p.chainId]||p.chainId;return '<div class="pt-nb-sr-row" data-action="tok" data-mint="'+esc(addr)+'" data-chain="'+esc(p.chainId)+'">'+logoTile(img,sym,'pt-nb-sr-logo','pt-nb-sr-logo-ph')+'<div class="pt-nb-sr-name">$'+esc(sym)+' <span class="pt-nb-sr-chain">'+esc(chainLbl)+'</span></div><div class="pt-nb-sr-sub">'+fmtPrice(p.priceUsd)+'</div></div>';}).join('');if(users.length)html+='<div class="pt-nb-sr-hd">Traders</div>'+users.slice(0,5).map(function(u){return '<div class="pt-nb-sr-row" data-action="trader" data-wallet="'+esc(u.wallet)+'">'+logoTile(u.avatar_url,u.username,'pt-nb-sr-logo','pt-nb-sr-logo-ph')+'<div class="pt-nb-sr-name">'+esc(u.username||'')+'</div></div>';}).join('');searchRes.innerHTML=html||'<div class="pt-nb-sr-empty">No results</div>';searchRes.classList.add('open');});}
  if(searchRes)searchRes.addEventListener('click',function(e){var tok=e.target.closest('[data-action="tok"]');if(tok){window.location.href='/live-market?mint='+encodeURIComponent(tok.dataset.mint);return;}var trader=e.target.closest('[data-action="trader"]');if(trader)window.location.href='/profile/'+encodeURIComponent(trader.dataset.wallet);});
  fetch('/api/me',{credentials:'include'}).then(function(r){return r.json();}).then(function(d){if(!d||!d.ok)return;var balEl=document.getElementById('pt-nb-sol-balance');if(balEl)balEl.textContent=Number(d.balance||0).toFixed(2);if(d.avatar){var img=document.getElementById('pt-nb-avatar'),ph=document.getElementById('pt-nb-avatar-ph');if(img){img.src=d.avatar;img.style.display='block';}if(ph)ph.style.display='none';}if(d.is_admin)document.querySelectorAll('.pt-nb-admin-link').forEach(function(x){x.style.display='flex';});}).catch(function(){});
  function refreshBadges(){fetch('/api/messages/unread_count',{credentials:'include'}).then(function(r){return r.json();}).then(function(d){var n=(d&&d.count)||0;['pt-nb-msg-badge','pt-nb-more-msg-badge'].forEach(function(id){var el=document.getElementById(id);if(!el)return;el.textContent=n>99?'99+':String(n);el.classList.toggle('show',n>0);});}).catch(function(){});fetch('/api/notifications/mine/unread_count',{credentials:'include'}).then(function(r){return r.json();}).then(function(d){var n=(d&&d.ok&&d.unread)||0;['pt-nb-notif-badge','pt-nb-more-notif-badge'].forEach(function(id){var el=document.getElementById(id);if(!el)return;el.textContent=n>99?'99+':String(n);el.classList.toggle('show',n>0);});}).catch(function(){});}
  refreshBadges();setInterval(refreshBadges,30000);
});
})();
