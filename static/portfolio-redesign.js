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
function removeLegacyHistoryCards(){
  /* The old Wallet template contains Recent activity, Bridge History and
     Trade History cards. Bot trades belong on /history and bridge diagnostics
     do not belong in Portfolio. Portfolio now has one dedicated Live Market
     transaction card injected separately, so remove every legacy act-card. */
  document.querySelectorAll('.act-card').forEach(function(card){card.remove()});
}
function boot(){
  if(location.pathname.replace(/\/+$/,'')!=='/wallet'){revealPortfolio();return}
  if(document.body.classList.contains('oa-portfolio')){removeLegacyHistoryCards();revealWhenStyled();return}
  document.body.classList.add('oa-portfolio','pf-view-overview');
  document.title='Portfolio — OrcAgent';

  var title=document.querySelector('.wlt-title'),sub=document.querySelector('.wlt-sub');
  if(title)title.textContent='Portfolio';
  if(sub)sub.textContent='Your complete multi-chain trading portfolio';
  document.querySelectorAll('a[href="/wallet"],a[href^="/wallet?"]').forEach(function(a){var text=(a.textContent||'').trim();if(/wallet/i.test(text))a.textContent=text.replace(/wallet/ig,'Portfolio');a.setAttribute('aria-label','Portfolio')});

  var center=document.querySelector('.wlt-center'),hdr=document.querySelector('.wlt-hdr'),content=document.querySelector('.wlt-content');
  if(!center||!hdr||!content){revealPortfolio();return}

  var tabs=document.createElement('div');
  tabs.className='pf-tabs';
  tabs.innerHTML='<button class="pf-tab active" data-pf-view="overview">Overview</button><button class="pf-tab" data-pf-view="deposit">Deposit</button><button class="pf-tab" data-pf-view="withdraw">Withdraw</button>';
  hdr.insertAdjacentElement('afterend',tabs);

  var hero=document.createElement('section');
  hero.className='pf-balance-card';
  hero.innerHTML='<div class="pf-kicker">Total portfolio value</div><div class="pf-balance" id="pf-total">$0.00</div><div class="pf-change" id="pf-change"><span>Multi-chain</span><span class="muted">live balances</span></div><div class="pf-actions"><button class="pf-action deposit" id="pf-deposit">↓ <span>Deposit</span></button><button class="pf-action withdraw" id="pf-withdraw">⇧ <span>Withdraw</span></button></div>';
  content.insertBefore(hero,content.firstChild);

  var allocation=document.createElement('section');
  allocation.className='pf-allocation';
  allocation.innerHTML='<div class="pf-donut" id="pf-donut"><div class="pf-donut-center" id="pf-donut-total">$0.00</div></div><div class="pf-legend"><div class="pf-leg-row"><span class="pf-dot a"></span><span class="pf-leg-name" id="pf-a-name">USDC</span><span class="pf-leg-val" id="pf-a-val">—</span></div><div class="pf-leg-row"><span class="pf-dot b"></span><span class="pf-leg-name" id="pf-b-name">SOL</span><span class="pf-leg-val" id="pf-b-val">—</span></div><div class="pf-leg-row"><span class="pf-dot c"></span><span class="pf-leg-name" id="pf-c-name">Other</span><span class="pf-leg-val" id="pf-c-val">—</span></div></div>';
  hero.insertAdjacentElement('afterend',allocation);

  var holdings=document.querySelector('.holdings');
  if(holdings){var ht=holdings.querySelector('.holdings-title');if(ht)ht.textContent='Assets'}
  removeLegacyHistoryCards();

  function showView(view){
    document.body.classList.remove('pf-view-overview','pf-view-deposit','pf-view-withdraw');
    if(view==='withdraw'){
      document.body.classList.add('pf-view-overview');
      tabs.querySelectorAll('.pf-tab').forEach(function(b){b.classList.toggle('active',b.dataset.pfView==='withdraw')});
      call('_modalSend');setTimeout(polishWithdrawModal,0);return;
    }
    document.body.classList.add('pf-view-'+view);
    tabs.querySelectorAll('.pf-tab').forEach(function(b){b.classList.toggle('active',b.dataset.pfView===view)});
    if(view==='deposit'){
      setTimeout(function(){var d=document.querySelector('.dep-card');if(!d)return;try{d.scrollIntoView({behavior:'smooth',block:'start'})}catch(e){try{d.scrollIntoView()}catch(_e){}}},30);
    }else{try{center.scrollTop=0}catch(e){}try{window.scrollTo(0,0)}catch(e){}}
  }
  tabs.addEventListener('click',function(e){var b=e.target.closest('[data-pf-view]');if(b)showView(b.dataset.pfView)});
  document.getElementById('pf-deposit').addEventListener('click',function(){showView('deposit')});
  document.getElementById('pf-withdraw').addEventListener('click',function(){showView('withdraw')});
  document.addEventListener('change',function(e){if(e.target&&e.target.id==='send-chain')setTimeout(polishWithdrawModal,0)});

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
