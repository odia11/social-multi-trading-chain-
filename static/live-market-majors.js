/* Native major-asset quotes stay separate from Solana token trading. */
(function(){
'use strict';
window.__oaMajorMarketProfile=false;
var symbol=new URLSearchParams(location.search).get('asset');
var names={BTC:'Bitcoin',ETH:'Ethereum'};
if(!Object.prototype.hasOwnProperty.call(names,symbol)) return;
window.__oaMajorMarketProfile=true;
var scope=window.__oaLiveMarketScope;
if(!scope) return;
scope.addEventListener(document,'DOMContentLoaded',function(){
  var root=document.querySelector('.pt-shell');
  if(!root) return;
  document.title=names[symbol]+' — Live Market — OrcAgent';
  document.body.classList.add('oa-major-profile');
  var style=document.createElement('style');
  style.textContent='body.oa-major-profile .pt-shell{display:block;max-width:760px;margin:auto;padding:20px 16px 120px}.oa-major-profile .major-panel{border:1px solid var(--line,#24313d);background:var(--card,#0d151e);border-radius:22px;padding:24px;color:var(--text,#eef1f5)}.major-back,.major-tabs a{display:inline-flex;align-items:center;min-height:44px;color:var(--amber,#f7b955);text-decoration:none}.major-tabs{display:flex;gap:24px;margin:18px 0}.major-tabs a[aria-current]{font-weight:800;text-decoration:underline;text-underline-offset:6px}.major-title{margin:8px 0;font-size:32px}.major-sub,.major-note,.major-status{color:var(--muted,#8e97a3);font-size:13px;line-height:1.6}.major-price{font:700 clamp(28px,7vw,44px)/1.4 system-ui,sans-serif;margin-top:24px;overflow-wrap:anywhere}.major-change{font-size:18px;color:#3ad29b;margin:8px 0 24px}.major-change.down{color:#ff7a88}.major-note{padding-top:18px;border-top:1px solid var(--line,#24313d)}';
  root.replaceChildren(style);
  var panel=document.createElement('section');panel.className='major-panel';
  panel.innerHTML='<a class="major-back" href="/live-market">← Live Market</a><nav class="major-tabs" aria-label="Major assets"><a href="/live-market?asset=BTC">BTC</a><a href="/live-market?asset=ETH">ETH</a><a href="/live-market?mint=So11111111111111111111111111111111111111112&amp;profile=1">SOL</a></nav><h1 class="major-title"></h1><div class="major-sub"></div><div class="major-price">—</div><div class="major-change">—</div><div class="major-status" role="status">Loading market price…</div><p class="major-note">Native asset · Price only<br>Trading on OrcAgent supports Solana tokens.</p>';
  panel.querySelector('.major-title').textContent=names[symbol];
  panel.querySelector('.major-sub').textContent=symbol+' / USD · Live Market';
  panel.querySelector('a[href="/live-market?asset='+symbol+'"]').setAttribute('aria-current','page');
  root.appendChild(panel);
  var busy=false;
  async function refresh(){
    if(busy||document.hidden||!panel.isConnected) return;
    busy=true;
    try{
      var response=await scope.fetch('/api/home/major-prices',{credentials:'same-origin',cache:'no-store'});
      if(!response.ok) throw Error('Quote unavailable');
      var data=await response.json(),quote=data.prices&&data.prices[symbol];
      if(!data.ok||!quote||!Number.isFinite(Number(quote.price))||Number(quote.price)<=0) throw Error('Quote unavailable');
      panel.querySelector('.major-price').textContent=Number(quote.price).toLocaleString('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2});
      var change=panel.querySelector('.major-change'),pct=Number(quote.change24h);
      change.textContent=Number.isFinite(pct)?(pct>=0?'+':'')+pct.toFixed(2)+'% · 24h':'24h change unavailable';
      change.classList.toggle('down',pct<0);
      panel.querySelector('.major-status').textContent=data.stale?'Last received price · temporarily delayed':'Updated '+new Date().toLocaleTimeString();
    }catch(_){panel.querySelector('.major-status').textContent='Market price temporarily unavailable. Retrying…';}
    finally{busy=false;}
  }
  window.OrcAgentRefreshLiveMarket=refresh;
  refresh();
  scope.setInterval(refresh,15000);
  scope.addEventListener(document,'visibilitychange',function(){if(!document.hidden)refresh();});
});
})();
