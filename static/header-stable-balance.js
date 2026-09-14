/* Live TOTAL multi-chain portfolio value in the shared top bar.
   On /wallet the Portfolio controller is authoritative; other pages poll a
   lightweight snapshot at a calm cadence so navigation stays responsive. */
(function(){
'use strict';
var timer=null,inFlight=false,last='',lastAt=0;
var here=location.pathname.replace(/\/+$/,'')||'/';
var ON_PORTFOLIO=here==='/wallet',POLL_MS=15000,MIN_GAP_MS=2500;
function el(){return document.getElementById('pt-nb-sol-balance')}
function n(v){v=Number(v||0);return isFinite(v)&&v>0?v:0}
function money(v){return '$'+n(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}
function render(value){var node=el();if(!node)return;node.textContent=value||'$0.00';node.setAttribute('aria-label','Total portfolio value '+(value||'$0.00'));var pill=node.closest('.pt-nb-balance,.pt-nb-sol,.pt-nb-wallet-balance')||node.parentElement;if(pill)pill.title='Live total portfolio value across OrcAgent chains'}
function json(url){var sep=url.indexOf('?')>=0?'&':'?';return fetch(url+sep+'t='+Date.now(),{credentials:'include',cache:'no-store'}).then(function(r){if(!r.ok)throw new Error('portfolio value unavailable');return r.json()})}
function calc(summary,tokBody,bal){summary=summary||{};tokBody=tokBody||{};bal=bal||{};var stable=n(summary.total_usdc!=null?summary.total_usdc:summary.total),tokens=Array.isArray(tokBody.tokens)?tokBody.tokens:[];var other=tokens.reduce(function(sum,x){var sym=String(x.symbol||x.ticker||'').toUpperCase();if(sym==='USDC'||sym==='USDT'||sym==='USDG'||sym==='SOL')return sum;var v=x.usd_value;if(v==null)v=x.value_usd;if(v==null)v=n(x.balance!=null?x.balance:x.amount)*n(x.price_usd!=null?x.price_usd:x.price);return sum+n(v)},0);var solPrice=n(bal.sol_price||summary.sol_price||window._wSolPrice||0);return stable+n(bal.sol)*solPrice+other}
function refresh(force){
  if(ON_PORTFOLIO){if(window.__orcaPortfolioValue!=null)render(money(window.__orcaPortfolioValue));return Promise.resolve()}
  if(inFlight||!el()||document.hidden)return Promise.resolve();
  var now=Date.now();if(!force&&now-lastAt<MIN_GAP_MS)return Promise.resolve();lastAt=now;inFlight=true;
  return Promise.allSettled([json('/api/wallet/usdc-summary'),json('/api/wallet/tokens?bust=1'),json('/api/wallet/balance')]).then(function(res){var s=res[0].status==='fulfilled'?res[0].value:{},t=res[1].status==='fulfilled'?res[1].value:{},b=res[2].status==='fulfilled'?res[2].value:{};if(res.every(function(x){return x.status==='rejected'}))throw new Error('all portfolio reads failed');var text=money(calc(s,t,b));last=text;render(text)}).catch(function(){if(last)render(last)}).finally(function(){inFlight=false})
}
function start(){
  if(!el())return;
  if(ON_PORTFOLIO){if(window.__orcaPortfolioValue!=null)render(money(window.__orcaPortfolioValue));return}
  refresh(true);if(timer)clearInterval(timer);timer=setInterval(function(){refresh(false)},POLL_MS)
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
document.addEventListener('orca:portfolio-value',function(e){var total=e&&e.detail&&e.detail.total;if(total!=null){last=money(total);render(last)}});
window.addEventListener('pageshow',function(){refresh(true)});
window.addEventListener('focus',function(){refresh(false)});
document.addEventListener('visibilitychange',function(){if(!document.hidden)refresh(false)});
window.OrcAgentRefreshStableBalance=function(){return refresh(true)};
window.OrcAgentRefreshPortfolioValue=function(){return refresh(true)};
})();
