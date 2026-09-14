/* Show the user's live TOTAL multi-chain portfolio value in the shared top bar.
   Total = stablecoins across chains + native SOL value + held token positions.
   This intentionally mirrors Portfolio's calculation so the number in the
   navbar and the number on /wallet cannot describe two different things. */
(function(){
'use strict';
var timer=null,inFlight=false,last='';

function el(){return document.getElementById('pt-nb-sol-balance')}
function n(v){v=Number(v||0);return isFinite(v)&&v>0?v:0}
function money(v){return '$'+n(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}
function render(value){
  var node=el();
  if(!node)return;
  node.textContent=value||'$0.00';
  node.setAttribute('aria-label','Total portfolio value '+(value||'$0.00'));
  var pill=node.closest('.pt-nb-balance,.pt-nb-sol,.pt-nb-wallet-balance')||node.parentElement;
  if(pill) pill.title='Live total portfolio value across OrcAgent chains';
}
function json(url){
  var sep=url.indexOf('?')>=0?'&':'?';
  return fetch(url+sep+'t='+Date.now(),{credentials:'include',cache:'no-store'})
    .then(function(r){if(!r.ok)throw new Error('portfolio value unavailable');return r.json()});
}
function calc(summary,tokBody,bal){
  summary=summary||{};tokBody=tokBody||{};bal=bal||{};
  var stable=n(summary.total_usdc!=null?summary.total_usdc:summary.total);
  var tokens=Array.isArray(tokBody.tokens)?tokBody.tokens:[];

  /* /api/wallet/tokens may contain USDC and SOL as well. They are already
     represented by `stable` and `solValue`, so only count non-stable,
     non-native holdings here. This also includes BSC/Base/ARB/POLY/HOOD
     positions appended by portfolio_multichain_holdings.py. */
  var other=tokens.reduce(function(sum,x){
    var sym=String(x.symbol||x.ticker||'').toUpperCase();
    if(sym==='USDC'||sym==='USDT'||sym==='USDG'||sym==='SOL')return sum;
    var v=x.usd_value;if(v==null)v=x.value_usd;
    if(v==null)v=n(x.balance!=null?x.balance:x.amount)*n(x.price_usd!=null?x.price_usd:x.price);
    return sum+n(v);
  },0);
  var solPrice=n(bal.sol_price||summary.sol_price||window._wSolPrice||0);
  var solValue=n(bal.sol)*solPrice;
  return stable+solValue+other;
}
function refresh(){
  if(inFlight||!el())return Promise.resolve();
  inFlight=true;
  return Promise.allSettled([
    json('/api/wallet/usdc-summary'),
    json('/api/wallet/tokens?bust=1'),
    json('/api/wallet/balance')
  ]).then(function(res){
    var s=res[0].status==='fulfilled'?res[0].value:{};
    var t=res[1].status==='fulfilled'?res[1].value:{};
    var b=res[2].status==='fulfilled'?res[2].value:{};
    /* Do not overwrite a known real value with $0 because one RPC timed out. */
    if(res.every(function(x){return x.status==='rejected'}))throw new Error('all portfolio reads failed');
    var text=money(calc(s,t,b));last=text;render(text);
  }).catch(function(){if(last)render(last)}).finally(function(){inFlight=false});
}
function start(){
  if(!el())return;
  refresh();
  setTimeout(refresh,500); /* wins any later legacy /api/me SOL paint */
  if(timer)clearInterval(timer);
  timer=setInterval(function(){if(!document.hidden)refresh()},5000);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
window.addEventListener('pageshow',refresh);
window.addEventListener('focus',refresh);
document.addEventListener('visibilitychange',function(){if(!document.hidden)refresh()});
document.addEventListener('orca:portfolio-changed',refresh);
/* Keep the old public name for compatibility with existing callers, but its
   meaning is now the product-correct total portfolio value. */
window.OrcAgentRefreshStableBalance=refresh;
window.OrcAgentRefreshPortfolioValue=refresh;
})();
