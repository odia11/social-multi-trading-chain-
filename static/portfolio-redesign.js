/* Portfolio presentation layer for /wallet.
   It deliberately reuses the wallet page's existing functions/endpoints so
   Deposit, Withdraw/Send, Swap, holdings, bridge history and trade history
   keep the same server-side routes and safety checks. */
(function(){
'use strict';
var _revealed=false;
function revealPortfolio(){
  if(_revealed) return;
  _revealed=true;
  document.documentElement.classList.remove('oa-pf-boot');
  var boot=document.getElementById('oa-pf-boot-style');
  if(boot) boot.remove();
}
function revealWhenStyled(){
  var css=document.querySelector('link[href*="portfolio-redesign.css"]');
  function done(){ requestAnimationFrame(function(){ requestAnimationFrame(revealPortfolio); }); }
  if(css && !css.sheet){
    css.addEventListener('load',done,{once:true});
    css.addEventListener('error',done,{once:true});
    setTimeout(done,1500);
  } else done();
}
function money(v){
  var n=Number(v||0); if(!isFinite(n)) n=0;
  return new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:2,maximumFractionDigits:2}).format(n);
}
function num(v){ var n=Number(v||0); return isFinite(n)?n:0; }
function call(name){
  var fn=window[name];
  if(typeof fn==='function') return fn.apply(window,Array.prototype.slice.call(arguments,1));
}

/* IMPORTANT: this function must be idempotent. The previous implementation
   rewrote an already-sanitised em dash on every MutationObserver callback.
   Setting textContent itself creates another mutation, which produced an
   endless observer loop and could peg iOS Safari's main thread at 100%.
   We now mark sanitised nodes and never write the same value twice. */
function sanitizeAssetPercentages(root){
  (root||document).querySelectorAll('.tok-pct').forEach(function(el){
    if(el.dataset.pfSanitized==='1') return;
    var text=(el.textContent||'').trim();
    if(text==='—'){
      el.dataset.pfSanitized='1';
      return;
    }
    var raw=text.replace(/,/g,'').replace(/[^0-9+\-.]/g,'');
    var n=parseFloat(raw);
    if(!isFinite(n) || Math.abs(n)>1000){
      el.dataset.pfSanitized='1';
      if(el.textContent!=='—') el.textContent='—';
      el.style.color='var(--muted,#6f7885)';
      el.title='24h change unavailable';
    }
  });
}

/* The wallet transaction code still uses the historical Send naming.
   Portfolio presents the same tested flow as Withdraw without touching the
   routing, validation, fee reserve or MAX calculations underneath. */
function polishWithdrawModal(){
  var modal=document.getElementById('w-modal');
  if(!modal || modal.style.display==='none') return;
  var title=modal.querySelector('.w-modal-title');
  if(title && /^\s*Send\s*$/i.test(title.textContent||'')) title.textContent='Withdraw';
  var btn=document.getElementById('send-btn');
  if(btn){
    var text=(btn.textContent||'').trim();
    if(/^Send\b/i.test(text)) btn.textContent=text.replace(/^Send\b/i,'Withdraw');
  }
}

function boot(){
  if(location.pathname.replace(/\/+$/,'')!=='/wallet'){ revealPortfolio(); return; }
  if(document.body.classList.contains('oa-portfolio')){ revealWhenStyled(); return; }
  document.body.classList.add('oa-portfolio','pf-view-overview');
  document.title='Portfolio — OrcAgent';

  var title=document.querySelector('.wlt-title');
  var sub=document.querySelector('.wlt-sub');
  if(title) title.textContent='Portfolio';
  if(sub) sub.textContent='Your complete multi-chain trading portfolio';

  document.querySelectorAll('a[href="/wallet"],a[href^="/wallet?"]').forEach(function(a){
    var text=(a.textContent||'').trim();
    if(/wallet/i.test(text)) a.textContent=text.replace(/wallet/ig,'Portfolio');
    a.setAttribute('aria-label','Portfolio');
  });

  var center=document.querySelector('.wlt-center');
  var hdr=document.querySelector('.wlt-hdr');
  var content=document.querySelector('.wlt-content');
  if(!center||!hdr||!content){ revealPortfolio(); return; }

  var tabs=document.createElement('div');
  tabs.className='pf-tabs';
  tabs.innerHTML='<button class="pf-tab active" data-pf-view="overview">Overview</button>'+
    '<button class="pf-tab" data-pf-view="deposit">Deposit</button>'+
    '<button class="pf-tab" data-pf-view="withdraw">Withdraw</button>';
  hdr.insertAdjacentElement('afterend',tabs);

  var hero=document.createElement('section');
  hero.className='pf-balance-card';
  hero.innerHTML='<div class="pf-kicker">Total portfolio value</div>'+
    '<div class="pf-balance" id="pf-total">$0.00</div>'+
    '<div class="pf-change" id="pf-change"><span>Multi-chain</span><span class="muted">live balances</span></div>'+
    '<div class="pf-actions">'+
      '<button class="pf-action deposit" id="pf-deposit">↓ <span>Deposit</span></button>'+
      '<button class="pf-action withdraw" id="pf-withdraw">⇧ <span>Withdraw</span></button>'+
    '</div>';
  content.insertBefore(hero,content.firstChild);

  var allocation=document.createElement('section');
  allocation.className='pf-allocation';
  allocation.innerHTML='<div class="pf-donut" id="pf-donut"><div class="pf-donut-center" id="pf-donut-total">$0.00</div></div>'+
    '<div class="pf-legend">'+
      '<div class="pf-leg-row"><span class="pf-dot a"></span><span class="pf-leg-name" id="pf-a-name">USDC</span><span class="pf-leg-val" id="pf-a-val">—</span></div>'+
      '<div class="pf-leg-row"><span class="pf-dot b"></span><span class="pf-leg-name" id="pf-b-name">SOL</span><span class="pf-leg-val" id="pf-b-val">—</span></div>'+
      '<div class="pf-leg-row"><span class="pf-dot c"></span><span class="pf-leg-name" id="pf-c-name">Other</span><span class="pf-leg-val" id="pf-c-val">—</span></div>'+
    '</div>';
  hero.insertAdjacentElement('afterend',allocation);

  var holdings=document.querySelector('.holdings');
  if(holdings){ var ht=holdings.querySelector('.holdings-title'); if(ht) ht.textContent='Assets'; }
  document.querySelectorAll('.act-card').forEach(function(el,i){ if(i>0) el.dataset.pfExtra='1'; });

  function showView(view){
    document.body.classList.remove('pf-view-overview','pf-view-deposit','pf-view-withdraw');
    if(view==='withdraw'){
      document.body.classList.add('pf-view-overview');
      tabs.querySelectorAll('.pf-tab').forEach(function(b){b.classList.toggle('active',b.dataset.pfView==='withdraw');});
      call('_modalSend');
      setTimeout(polishWithdrawModal,0);
      return;
    }
    document.body.classList.add('pf-view-'+view);
    tabs.querySelectorAll('.pf-tab').forEach(function(b){b.classList.toggle('active',b.dataset.pfView===view);});
    if(view==='deposit'){
      /* Portfolio deposit is a dedicated multi-chain view. The underlying
         .dep-card already owns Solana + EVM address selection, copy and
         explorer behaviour. Do not open the legacy Solana-only modal. */
      setTimeout(function(){
        var d=document.querySelector('.dep-card');
        if(!d) return;
        try{ d.scrollIntoView({behavior:'smooth',block:'start'}); }catch(e){ try{ d.scrollIntoView(); }catch(_e){} }
      },30);
    } else {
      try{ center.scrollTop=0; }catch(e){}
      try{ window.scrollTo(0,0); }catch(e){}
    }
  }
  tabs.addEventListener('click',function(e){var b=e.target.closest('[data-pf-view]');if(b)showView(b.dataset.pfView);});
  document.getElementById('pf-deposit').addEventListener('click',function(){ showView('deposit'); });
  document.getElementById('pf-withdraw').addEventListener('click',function(){showView('withdraw');});

  /* The legacy chain sync function rewrites the primary button back to
     "Send <asset>" after a network change. Let it finish, then restore the
     Portfolio wording. This does not alter the selected chain or payload. */
  document.addEventListener('change',function(e){
    if(e.target && e.target.id==='send-chain') setTimeout(polishWithdrawModal,0);
  });

  var oldAvail=document.getElementById('avail');
  if(oldAvail && window.MutationObserver){
    new MutationObserver(function(){
      var raw=(oldAvail.textContent||'').replace(/,/g,'').replace(/[^0-9.\-]/g,'');
      if(raw) document.getElementById('pf-total').textContent=money(raw);
    }).observe(oldAvail,{childList:true,characterData:true,subtree:true});
  }

  /* Observe only structural updates from the wallet token loader. We do NOT
     observe characterData: sanitising text is itself a text mutation and was
     the source of the recursive freeze. A small debounce also coalesces a
     batch of token rows into one pass. */
  if(holdings && window.MutationObserver){
    var pctTimer=null;
    new MutationObserver(function(){
      clearTimeout(pctTimer);
      pctTimer=setTimeout(function(){sanitizeAssetPercentages(holdings);},0);
    }).observe(holdings,{childList:true,subtree:true});
    sanitizeAssetPercentages(holdings);
  }

  /* The Portfolio shell is now fully built. Reveal only after its stylesheet
     is actually applied, so the legacy Wallet markup can never flash first. */
  revealWhenStyled();

  Promise.allSettled([
    fetch('/api/wallet/usdc-summary',{credentials:'include'}).then(function(r){return r.json();}),
    fetch('/api/wallet/tokens',{credentials:'include'}).then(function(r){return r.json();}),
    fetch('/api/wallet/balance',{credentials:'include'}).then(function(r){return r.json();})
  ]).then(function(res){
    var s=res[0].status==='fulfilled'?res[0].value||{}:{};
    var t=res[1].status==='fulfilled'?res[1].value||{}:{};
    var b=res[2].status==='fulfilled'?res[2].value||{}:{};
    var usdc=num(s.total_usdc!=null?s.total_usdc:(s.total!=null?s.total:0));
    var tokens=Array.isArray(t.tokens)?t.tokens:[];
    var tokenValue=tokens.reduce(function(sum,x){
      var v=x.usd_value; if(v==null)v=x.value_usd; if(v==null)v=num(x.balance||x.amount)*num(x.price_usd||x.price);
      return sum+num(v);
    },0);
    var solPrice=num(b.sol_price||s.sol_price||0);
    var solValue=num(b.sol)*solPrice;
    var otherValue=tokens.reduce(function(sum,x){
      var sym=String(x.symbol||x.ticker||'').toUpperCase(); if(sym==='USDC'||sym==='USDT'||sym==='SOL') return sum;
      var v=x.usd_value; if(v==null)v=x.value_usd; if(v==null)v=num(x.balance||x.amount)*num(x.price_usd||x.price);
      return sum+num(v);
    },0);
    if(!otherValue && tokenValue>usdc) otherValue=Math.max(0,tokenValue-usdc-solValue);
    var total=Math.max(usdc+solValue+otherValue,usdc,tokenValue);
    document.getElementById('pf-total').textContent=money(total);
    document.getElementById('pf-donut-total').textContent=total>=1000?'$'+(total/1000).toFixed(total>=10000?0:1)+'k':money(total);
    var vals=[usdc,solValue,otherValue],sum=vals.reduce(function(a,c){return a+c;},0)||1;
    var p1=Math.max(0,Math.min(100,vals[0]/sum*100));
    var p2=Math.max(0,Math.min(100-p1,vals[1]/sum*100));
    document.getElementById('pf-donut').style.background='conic-gradient(var(--pf-yellow) 0 '+p1.toFixed(1)+'%,#7ed797 '+p1.toFixed(1)+'% '+(p1+p2).toFixed(1)+'%,#7b8ca6 '+(p1+p2).toFixed(1)+'% 100%)';
    function setRow(prefix,name,value){
      document.getElementById(prefix+'-name').textContent=name;
      document.getElementById(prefix+'-val').textContent=(value/sum*100).toFixed(1)+'%';
    }
    setRow('pf-a','USDC',usdc);setRow('pf-b','SOL',solValue);setRow('pf-c','Other',otherValue);
    sanitizeAssetPercentages(document);
  }).catch(function(){});
}
if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot); else boot();
})();
