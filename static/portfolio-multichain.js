/* Multi-chain Portfolio presentation/safety layer.
   Keeps holdings current without hammering wallet/RPC endpoints. */
(function(){
'use strict';
if((location.pathname.replace(/\/+$/,'')||'/')!=='/wallet') return;

var LABELS={bsc:'BSC',base:'BASE',arbitrum:'ARB',polygon:'POLY',robinhood:'HOOD',solana:'SOL'};
var _refreshing=false,_refreshTimer=null,_lastRefresh=0,_pendingTimer=null;
var AUTO_REFRESH_MS=15000,MIN_REFRESH_GAP_MS=1800;
var _latest={summary:null,tokens:null,balance:null};

function list(){ return window._wTokens||window._allSpl||[]; }
function num(v){v=Number(v||0);return isFinite(v)&&v>0?v:0}
function money(v){return '$'+num(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}
function indexFromButton(btn){
  var m=(btn.getAttribute('onclick')||'').match(/_toggleTokTrade\((\d+)\)/);
  return m?Number(m[1]):-1;
}
function decorate(){
  document.querySelectorAll('.tok-row-block').forEach(function(block){
    var btn=block.querySelector('.tok-trade-btn');
    if(!btn)return;
    var i=indexFromButton(btn),t=list()[i];
    if(!t)return;
    var chain=String(t.chain||'solana').toLowerCase();
    if(chain==='solana')return;
    block.dataset.chain=chain;
    var name=block.querySelector('.tok-name');
    if(name&&!name.querySelector('.oa-chain-badge')){
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
  if(!btn)return;
  var i=indexFromButton(btn),t=list()[i];
  if(!t)return;
  var chain=String(t.chain||'solana').toLowerCase();
  if(chain==='solana')return;
  e.preventDefault();e.stopPropagation();if(e.stopImmediatePropagation)e.stopImmediatePropagation();
  var addr=t.token_address||t.address||t.mint||'';
  window.location.href='/live-market?mint='+encodeURIComponent(addr)+'&chain='+encodeURIComponent(chain);
},true);

var style=document.createElement('style');
style.textContent='.oa-chain-badge{display:inline-flex;align-items:center;margin-left:7px;padding:2px 6px;border:1px solid rgba(247,185,85,.28);border-radius:999px;color:#f7b955;background:rgba(247,185,85,.08);font-size:9px;font-weight:800;letter-spacing:.06em;vertical-align:middle}.tok-row-block[data-chain="robinhood"] .oa-chain-badge{color:#d9b7ff;border-color:rgba(217,183,255,.28);background:rgba(217,183,255,.08)}';
document.head.appendChild(style);

function json(url){
  var sep=url.indexOf('?')>=0?'&':'?';
  return fetch(url+sep+'t='+Date.now(),{credentials:'include',cache:'no-store'})
    .then(function(r){if(!r.ok)throw new Error('read failed');return r.json()});
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
  var donutTotal=document.getElementById('pf-donut-total');if(donutTotal)donutTotal.textContent=total>=1000?'$'+(total/1000).toFixed(total>=10000?0:1)+'k':money(total);
  var sum=total||1,p1=Math.max(0,Math.min(100,stable/sum*100)),p2=Math.max(0,Math.min(100-p1,solValue/sum*100));
  var donut=document.getElementById('pf-donut');if(donut)donut.style.background='conic-gradient(var(--pf-yellow) 0 '+p1.toFixed(1)+'%,#7ed797 '+p1.toFixed(1)+'% '+(p1+p2).toFixed(1)+'%,#7b8ca6 '+(p1+p2).toFixed(1)+'% 100%)';
  [['pf-a',stable],['pf-b',solValue],['pf-c',other]].forEach(function(x){var e=document.getElementById(x[0]+'-val');if(e)e.textContent=(x[1]/sum*100).toFixed(1)+'%';});
  window.__orcaPortfolioValue=total;
  document.dispatchEvent(new CustomEvent('orca:portfolio-value',{detail:{total:total}}));
}

function refreshPortfolio(forceHoldings){
  if(document.hidden)return Promise.resolve();
  var now=Date.now();
  if(_refreshing)return Promise.resolve();
  if(!forceHoldings&&now-_lastRefresh<MIN_REFRESH_GAP_MS)return Promise.resolve();
  _refreshing=true;_lastRefresh=now;

  /* One authoritative snapshot for value calculation. The old implementation
     also called loadTokens/loadUsdcSummary/loadBalance AND fetched the same
     three endpoints again every 4s, which produced visible jank on iPhone. */
  var reads=[json('/api/wallet/usdc-summary'),json('/api/wallet/tokens?bust=1'),json('/api/wallet/balance')];
  if(forceHoldings&&typeof window.loadTokens==='function'){
    try{window.loadTokens(true);}catch(e){}
  }
  return Promise.allSettled(reads).then(function(r){
    if(r[0].status==='fulfilled')_latest.summary=r[0].value;
    if(r[1].status==='fulfilled')_latest.tokens=r[1].value;
    if(r[2].status==='fulfilled')_latest.balance=r[2].value;
    if(_latest.summary||_latest.tokens||_latest.balance)paintLiveValue(_latest.summary,_latest.tokens,_latest.balance);
    decorate();
    document.dispatchEvent(new CustomEvent('orca:portfolio-changed',{detail:{total:window.__orcaPortfolioValue||0}}));
  }).finally(function(){_refreshing=false});
}
function scheduleRefresh(forceHoldings,delay){
  if(_pendingTimer)clearTimeout(_pendingTimer);
  _pendingTimer=setTimeout(function(){_pendingTimer=null;refreshPortfolio(!!forceHoldings);},Math.max(0,delay||0));
}
function boot(){
  decorate();
  var h=document.querySelector('.holdings');
  if(h&&window.MutationObserver){
    var timer=null;
    new MutationObserver(function(){clearTimeout(timer);timer=setTimeout(decorate,80);}).observe(h,{childList:true,subtree:true});
  }
  scheduleRefresh(true,40);
  /* A second lightweight read catches a just-settled route without re-rendering
     the entire holdings list and without creating a request storm. */
  setTimeout(function(){refreshPortfolio(false);},1400);
  if(_refreshTimer)clearInterval(_refreshTimer);
  _refreshTimer=setInterval(function(){refreshPortfolio(false);},AUTO_REFRESH_MS);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
window.addEventListener('pageshow',function(){scheduleRefresh(true,0)});
window.addEventListener('focus',function(){scheduleRefresh(false,100)});
document.addEventListener('visibilitychange',function(){if(!document.hidden)scheduleRefresh(false,100)});
document.addEventListener('orca:trade-complete',function(){scheduleRefresh(true,100)});
window.OrcAgentRefreshPortfolio=function(){return refreshPortfolio(true)};
window.OrcAgentRefreshPortfolioValue=function(){return refreshPortfolio(false)};
})();
