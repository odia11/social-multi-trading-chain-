/* Instant shared portfolio balance in the OrcAgent top bar.
   Paint the last confirmed value synchronously from localStorage so page
   navigation never flashes $0.00, then reconcile from the authoritative
   Solana portfolio snapshot in the background. */
(function(){
'use strict';
var timer=null,inFlight=false,last='',lastAt=0,lastStored=null,lastStoredAt=0;
var here=location.pathname.replace(/\/+$/,'')||'/';
var ON_PORTFOLIO=here==='/wallet',POLL_MS=5000,MIN_GAP_MS=1200;
var scopeNode=document.querySelector('[data-orca-wallet-scope]');
var scope=scopeNode?scopeNode.getAttribute('data-orca-wallet-scope'):'';
var STORAGE_KEY='orcaPortfolioLastConfirmedUSDCValue:v3:'+scope;
var STORAGE_AT_KEY='orcaPortfolioLastConfirmedUSDCValueAt:v3:'+scope;
var MAX_CACHE_AGE=86400000;

function el(){return document.getElementById('pt-nb-sol-balance')}
function n(v){if(v==null||v==='')return null;v=Number(v);return Number.isFinite(v)&&v>=0?v:null}
function money(v){var x=n(v);return x===null?'—':x.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})+' USDC'}
function render(value){
  var node=el();if(!node)return;
  if(node.textContent===value&&node.getAttribute('aria-label')==='Total portfolio value '+value)return;
  node.textContent=value||'—';
  node.setAttribute('aria-label','Total portfolio value '+(value||'unavailable'));
  var pill=node.closest('.pt-nb-balance,.pt-nb-sol,.pt-nb-wallet-balance')||node.parentElement;
  if(pill)pill.title='Estimated portfolio value in USDC; assets remain on Solana';
}
function remember(total){
  var value=n(total);if(value===null||!scope)return;
  if(value===lastStored && Date.now()-lastStoredAt<60000)return;
  try{
    localStorage.setItem(STORAGE_KEY,String(value));
    localStorage.setItem(STORAGE_AT_KEY,String(Date.now()));
    lastStored=value;lastStoredAt=Date.now();
  }catch(e){}
}
function recalled(){
  if(!scope)return null;
  try{
    var raw=localStorage.getItem(STORAGE_KEY),at=Number(localStorage.getItem(STORAGE_AT_KEY));
    if(raw===null)return null;
    var value=n(raw);
    if(value===null||!Number.isFinite(at)||at<=0||Date.now()-at>MAX_CACHE_AGE)return null;
    return value;
  }catch(e){return null}
}
function json(url){
  var sep=url.indexOf('?')>=0?'&':'?';
  return fetch(url+sep+'t='+Date.now(),{credentials:'include',cache:'no-store'})
    .then(function(r){if(!r.ok)throw new Error('portfolio unavailable');return r.json()});
}
function accept(total,persist){
  var value=n(total);if(value===null)return false;
  last=money(value);render(last);if(persist!==false)remember(value);return true;
}
function refresh(force){
  if(!el()||document.hidden)return Promise.resolve(false);
  if(ON_PORTFOLIO){
    if(window.__orcaPortfolioValue!=null)accept(window.__orcaPortfolioValue,false);
    return Promise.resolve(true);
  }
  if(inFlight)return Promise.resolve(false);
  var now=Date.now();if(!force&&now-lastAt<MIN_GAP_MS)return Promise.resolve(false);
  lastAt=now;inFlight=true;
  return json('/api/portfolio/snapshot').then(function(s){
    if(!s||!s.ok||!accept(s.total_usd,!s.stale&&s.inventory_complete!==false&&s.valuation_complete!==false))throw new Error('bad portfolio snapshot');
    window.__orcaPortfolioValue=Number(s.total_usd);
    return true;
  }).catch(function(){
    if(last)render(last);
    return false;
  }).finally(function(){inFlight=false});
}
function start(){
  if(!el())return;
  var cached=recalled();
  if(cached!==null){last=money(cached);render(last)}
  else if((el().textContent||'').trim()==='$0.00')render('—');

  if(ON_PORTFOLIO){
    if(window.__orcaPortfolioValue!=null)accept(window.__orcaPortfolioValue,false);
    return;
  }
  refresh(true);
  if(timer)clearInterval(timer);
  timer=setInterval(function(){refresh(false)},POLL_MS);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();

document.addEventListener('orca:portfolio-value',function(e){
  var total=e&&e.detail&&e.detail.total;
  if(total!=null)accept(total,!e.detail.stale&&e.detail.inventory_complete!==false&&e.detail.valuation_complete!==false);
});
window.addEventListener('pageshow',function(){start();refresh(true)});
window.addEventListener('focus',function(){refresh(true)});
document.addEventListener('visibilitychange',function(){if(!document.hidden)refresh(true)});
window.OrcAgentRefreshStableBalance=function(){return refresh(true)};
if(!ON_PORTFOLIO)window.OrcAgentRefreshPortfolioValue=function(){return refresh(true)};
})();
