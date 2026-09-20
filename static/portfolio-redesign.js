/* Portfolio presentation layer for /wallet.
   IMPORTANT: this file owns presentation only. Live balances, allocation and
   token values are owned exclusively by portfolio-multichain.js. Keeping one
   writer prevents the Portfolio total from oscillating between stable-only
   and multi-chain values on iOS/PWA. */
(function(){
'use strict';
if(location.pathname.replace(/\/+$/,'')==='/wallet')document.documentElement.classList.add('oa-portfolio-root');
var _revealed=false;
function revealPortfolio(){
  if(_revealed)return;
  _revealed=true;
  document.documentElement.classList.remove('oa-pf-boot');
  var boot=document.getElementById('oa-pf-boot-style');
  if(boot)boot.remove();
}
function revealWhenStyled(){
  var css=document.querySelector('link[href*="portfolio-redesign.css"]');
  function done(){requestAnimationFrame(function(){requestAnimationFrame(revealPortfolio)})}
  if(css&&!css.sheet){css.addEventListener('load',done,{once:true});css.addEventListener('error',done,{once:true});setTimeout(done,1500)}else done();
}
function call(name){var fn=window[name];if(typeof fn==='function')return fn.apply(window,Array.prototype.slice.call(arguments,1))}
function sanitizeAssetPercentages(root){
  (root||document).querySelectorAll('.tok-pct').forEach(function(el){
    if(el.dataset.pfSanitized==='1')return;
    var text=(el.textContent||'').trim();
    if(text==='—'){el.dataset.pfSanitized='1';return}
    var raw=text.replace(/,/g,'').replace(/[^0-9+\-.]/g,'');
    var n=parseFloat(raw);
    if(!isFinite(n)||Math.abs(n)>1000){el.dataset.pfSanitized='1';if(el.textContent!=='—')el.textContent='—';el.style.color='var(--muted,#6f7885)';el.title='24h change unavailable'}
  });
}
function polishWithdrawModal(){
  var modal=document.getElementById('w-modal');if(!modal||modal.style.display==='none')return;
  var title=modal.querySelector('.w-modal-title');if(title&&/^\s*Send\s*$/i.test(title.textContent||''))title.textContent='Withdraw';
  var btn=document.getElementById('send-btn');if(btn){var text=(btn.textContent||'').trim();if(/^Send\b/i.test(text))btn.textContent=text.replace(/^Send\b/i,'Withdraw')}
}
function removeLegacyHistoryCards(){ /* Preserve actual wallet and bridge history for the History tab. */ }
function boot(){
  if(location.pathname.replace(/\/+$/,'')!=='/wallet'){revealPortfolio();return}
  if(document.body.classList.contains('oa-portfolio')){revealWhenStyled();return}
  document.body.classList.add('oa-portfolio','pf-view-assets');
  document.title='Portfolio — OrcAgent';

  var title=document.querySelector('.wlt-title'),sub=document.querySelector('.wlt-sub');
  if(title)title.textContent='Portfolio';
  if(sub)sub.textContent='Your multi-chain trading wallet';
  document.querySelectorAll('a[href="/wallet"],a[href^="/wallet?"]').forEach(function(a){var text=(a.textContent||'').trim();if(/wallet/i.test(text))a.textContent=text.replace(/wallet/ig,'Portfolio');a.setAttribute('aria-label','Portfolio')});

  var center=document.querySelector('.wlt-center'),hdr=document.querySelector('.wlt-hdr'),content=document.querySelector('.wlt-content');
  if(!center||!hdr||!content){revealPortfolio();return}

  var tabs=document.querySelector('.portfolio-tabs');

  var hero=document.querySelector('.wlt-hero');

  /* No synthetic balance or allocation: the real wallet hero owns the live total. */

  var holdings=document.querySelector('.holdings');
  if(holdings){var ht=holdings.querySelector('.holdings-title');if(ht)ht.textContent='Assets'}
  removeLegacyHistoryCards();

  function showView(view){
    if(['assets','chains','history'].indexOf(view)===-1)view='assets';
    document.body.classList.remove('pf-view-overview','pf-view-deposit','pf-view-withdraw','pf-view-assets','pf-view-chains','pf-view-history');
    document.body.classList.add('pf-view-'+view);
    if(tabs)tabs.querySelectorAll('[data-portfolio-tab]').forEach(function(b){
      var active=b.dataset.portfolioTab===view;
      b.classList.toggle('selected',active);b.setAttribute('aria-selected',String(active));
    });
    if(view==='chains'){
      var e=document.getElementById('usdc-chain-tiles');
      var toggle=document.getElementById('usdc-tiles-toggle');
      if(e&&e.classList.contains('collapsed')&&toggle)toggle.click();
    }
  }
  if(tabs)tabs.addEventListener('click',function(e){
    var b=e.target.closest('[data-portfolio-tab]');
    if(b)showView(b.dataset.portfolioTab);
  });
  showView('assets');

  if(holdings&&window.MutationObserver){
    var pctTimer=null;
    new MutationObserver(function(){clearTimeout(pctTimer);pctTimer=setTimeout(function(){sanitizeAssetPercentages(holdings)},50)}).observe(holdings,{childList:true,subtree:true});
    sanitizeAssetPercentages(holdings);
  }

  revealWhenStyled();
  setTimeout(function(){if(typeof window.OrcAgentRefreshPortfolio==='function')window.OrcAgentRefreshPortfolio()},60);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
