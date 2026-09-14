/* Multi-chain Portfolio presentation/safety layer. */
(function(){
'use strict';
if((location.pathname.replace(/\/+$/,'')||'/')!=='/wallet') return;

var LABELS={bsc:'BSC',base:'BASE',arbitrum:'ARB',polygon:'POLY',robinhood:'HOOD',solana:'SOL'};
var _refreshing=false,_refreshTimer=null,_valueBusy=false;

function list(){ return window._wTokens||window._allSpl||[]; }
function num(v){v=Number(v||0);return isFinite(v)&&v>0?v:0}
function money(v){return '$'+num(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}
function indexFromButton(btn){
  var m=(btn.getAttribute('onclick')||'').match(/_toggleTokTrade\((\d+)\)/);
  return m?Number(m[1]):-1;
}
function decorate(){
  var rows=document.querySelectorAll('.tok-row-block');
  rows.forEach(function(block){
    var btn=block.querySelector('.tok-trade-btn');
    if(!btn) return;
    var i=indexFromButton(btn), t=list()[i];
    if(!t) return;
    var chain=String(t.chain||'solana').toLowerCase();
    if(chain==='solana') return;
    block.dataset.chain=chain;
    var name=block.querySelector('.tok-name');
    if(name && !name.querySelector('.oa-chain-badge')){
      var badge=document.createElement('span');
      badge.className='oa-chain-badge';
      badge.textContent=LABELS[chain]||chain.toUpperCase();
      name.appendChild(badge);
    }
    btn.title='Trade on '+(LABELS[chain]||chain);
    btn.setAttribute('aria-label',btn.title);
  });
}

document.addEventListener('click',function(e){
  var btn=e.target.closest('.tok-trade-btn');
  if(!btn) return;
  var i=indexFromButton(btn), t=list()[i];
  if(!t) return;
  var chain=String(t.chain||'solana').toLowerCase();
  if(chain==='solana') return;
  e.preventDefault(); e.stopPropagation(); if(e.stopImmediatePropagation)e.stopImmediatePropagation();
  var addr=t.token_address||t.address||t.mint||'';
  window.location.href='/live-market?mint='+encodeURIComponent(addr)+'&chain='+encodeURIComponent(chain);
},true);

var style=document.createElement('style');
style.textContent='.oa-chain-badge{display:inline-flex;align-items:center;margin-left:7px;padding:2px 6px;border:1px solid rgba(247,185,85,.28);border-radius:999px;color:#f7b955;background:rgba(247,185,85,.08);font-size:9px;font-weight:800;letter-spacing:.06em;vertical-align:middle}.tok-row-block[data-chain="robinhood"] .oa-chain-badge{color:#d9b7ff;border-color:rgba(217,183,255,.28);background:rgba(217,183,255,.08)}';
document.head.appendChild(style);

function json(url){
  var sep=url.indexOf('?')>=0?'&':'?';
  return fetch(url+sep+'t='+Date.now(),{credentials:'include',cache:'no-store'}).then(function(r){if(!r.ok)throw new Error('read failed');return r.json()});
}
function paintLiveValue(summary,tokBody,bal){
  summary=summary||{};tokBody=tokBody||{};bal=bal||{};
  var stable=num(summary.total_usdc!=null?summary.total_usdc:summary.total);
  var tokens=Array.isArray(tokBody.tokens)?tokBody.tokens:[];
  var other=tokens.reduce(function(sum,x){
    var sym=String(x.symbol||x.ticker||'').toUpperCase();
    if(sym==='USDC'||sym==='USDT'||sym==='USDG'||sym==='SOL')return sum;
    var v=x.usd_value;if(v==null)v=x.value_usd;
    if(v==null)v=num(x.balance!=null?x.balance:x.amount)*num(x.price_usd!=null?x.price_usd:x.price);
    return sum+num(v);
  },0);
  var solPrice=num(bal.sol_price||summary.sol_price||window._wSolPrice||0);
  var solValue=num(bal.sol)*solPrice;
  var total=stable+solValue+other;

  var totalEl=document.getElementById('pf-total');if(totalEl)totalEl.textContent=money(total);
  var donutTotal=document.getElementById('pf-donut-total');
  if(donutTotal)donutTotal.textContent=total>=1000?'$'+(total/1000).toFixed(total>=10000?0:1)+'k':money(total);
  var sum=total||1,vals=[stable,solValue,other];
  var p1=Math.max(0,Math.min(100,vals[0]/sum*100));
  var p2=Math.max(0,Math.min(100-p1,vals[1]/sum*100));
  var donut=document.getElementById('pf-donut');
  if(donut)donut.style.background='conic-gradient(var(--pf-yellow) 0 '+p1.toFixed(1)+'%,#7ed797 '+p1.toFixed(1)+'% '+(p1+p2).toFixed(1)+'%,#7b8ca6 '+(p1+p2).toFixed(1)+'% 100%)';
  [['pf-a',stable],['pf-b',solValue],['pf-c',other]].forEach(function(x){var e=document.getElementById(x[0]+'-val');if(e)e.textContent=(x[1]/sum*100).toFixed(1)+'%';});
  document.dispatchEvent(new CustomEvent('orca:portfolio-value',{detail:{total:total}}));
}
function refreshLiveValue(){
  if(_valueBusy||document.hidden)return Promise.resolve();
  _valueBusy=true;
  return Promise.allSettled([json('/api/wallet/usdc-summary'),json('/api/wallet/tokens?bust=1'),json('/api/wallet/balance')]).then(function(r){
    var s=r[0].status==='fulfilled'?r[0].value:{};
    var t=r[1].status==='fulfilled'?r[1].value:{};
    var b=r[2].status==='fulfilled'?r[2].value:{};
    if(!r.every(function(x){return x.status==='rejected'}))paintLiveValue(s,t,b);
  }).finally(function(){_valueBusy=false});
}

/* Keep Portfolio live. A successful buy is recorded by the trading route
   before it answers success. Re-read with cache busting so the new position
   appears without a manual reload. */
function refreshPortfolio(){
  if(_refreshing||document.hidden)return Promise.resolve();
  _refreshing=true;
  var jobs=[];
  try{if(typeof window.loadTokens==='function')jobs.push(Promise.resolve(window.loadTokens(true)));}catch(e){}
  try{if(typeof window.loadUsdcSummary==='function')jobs.push(Promise.resolve(window.loadUsdcSummary()));}catch(e){}
  try{if(typeof window.loadBalance==='function')jobs.push(Promise.resolve(window.loadBalance()));}catch(e){}
  jobs.push(refreshLiveValue());
  return Promise.allSettled(jobs).then(function(){
    decorate();
    document.dispatchEvent(new CustomEvent('orca:portfolio-changed'));
  }).finally(function(){_refreshing=false});
}

function boot(){
  decorate();
  var h=document.querySelector('.holdings');
  if(h&&window.MutationObserver){
    var timer=null;
    new MutationObserver(function(){clearTimeout(timer);timer=setTimeout(function(){decorate();refreshLiveValue();},0);}).observe(h,{childList:true,subtree:true});
  }
  /* portfolio-redesign historically copied the stablecoin-only hero value into
     pf-total whenever `#avail` changed. Observe that same source and repaint
     the true multi-chain total immediately afterwards. */
  var avail=document.getElementById('avail');
  if(avail&&window.MutationObserver){
    var valueTimer=null;
    new MutationObserver(function(){clearTimeout(valueTimer);valueTimer=setTimeout(refreshLiveValue,0);}).observe(avail,{childList:true,characterData:true,subtree:true});
  }
  setTimeout(refreshPortfolio,80);
  setTimeout(refreshPortfolio,900);
  _refreshTimer=setInterval(refreshPortfolio,4000);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
window.addEventListener('pageshow',function(){setTimeout(refreshPortfolio,0)});
window.addEventListener('focus',refreshPortfolio);
document.addEventListener('visibilitychange',function(){if(!document.hidden)refreshPortfolio()});
document.addEventListener('orca:trade-complete',refreshPortfolio);
window.OrcAgentRefreshPortfolio=refreshPortfolio;
window.OrcAgentRefreshPortfolioValue=refreshLiveValue;
})();
