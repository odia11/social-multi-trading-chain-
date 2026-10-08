/* Real OrcAgent balances only. Never invent token rows, returns, or 24h PnL. */
(function(){
'use strict';
if((location.pathname.replace(/\/+$/,'')||'/')!=='/wallet')return;
var samples=[];
var scopeTag=document.querySelector('[data-orca-wallet-scope]');
var scope=scopeTag?scopeTag.getAttribute('data-orca-wallet-scope'):'';
var STORAGE_KEY='orcaPortfolioLastConfirmedUSDCValue:v3:'+scope;
var STORAGE_AT_KEY='orcaPortfolioLastConfirmedUSDCValueAt:v3:'+scope;
function remember(total){if(!scope)return;try{localStorage.setItem(STORAGE_KEY,String(total));localStorage.setItem(STORAGE_AT_KEY,String(Date.now()))}catch(e){}}
function recalled(){if(!scope)return null;try{var raw=localStorage.getItem(STORAGE_KEY),stamp=localStorage.getItem(STORAGE_AT_KEY);if(raw===null||stamp===null)return null;var n=Number(raw),at=Number(stamp);if(!Number.isFinite(n)||n<0||!Number.isFinite(at)||at<=0||Date.now()-at>86400000)return null;return n}catch(e){return null}}
function money(n){
  n=Number(n);
  return Number.isFinite(n)?n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})+' USDC':'—';
}
function put(id,value){var e=document.getElementById(id);if(e)e.textContent=value}
function spark(){
  var line=document.getElementById('pf-spark-line'),fill=document.getElementById('pf-spark-fill');
  if(!line||!fill||!samples.length)return;
  /* One confirmed sample still paints an immediate flat live baseline instead
     of leaving the chart blank until a second network poll completes. */
  if(samples.length===1){
    line.setAttribute('d','M3 38 L119 38');
    fill.setAttribute('d','M3 38 L119 38 L119 72 L3 72 Z');
    return;
  }
  var min=Math.min.apply(null,samples),max=Math.max.apply(null,samples);
  var spread=max-min,coords=samples.map(function(value,i){
    var x=3+i*116/Math.max(1,samples.length-1);
    var y=spread>0?62-(value-min)/spread*49:36;
    return [x,y];
  });
  var d=coords.map(function(p,i){return(i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)}).join(' ');
  line.setAttribute('d',d);
  fill.setAttribute('d',d+' L '+coords[coords.length-1][0].toFixed(1)+' 72 L 3 72 Z');
}
function paint(value){
  var d=value&&value.detail||{},total=d.total==null?NaN:Number(d.total);
  if(!Number.isFinite(total)||total<0)return;
  put('pf-total',money(total));
  put('pf-sol-equivalent',d.total_sol==null?'SOL equivalent unavailable':'≈ '+Number(d.total_sol).toLocaleString('en-US',{maximumFractionDigits:4})+' SOL');
  if(d.stale||d.inventory_complete===false){put('pf-performance','Refreshing…');return;}
  if(d.valuation_complete===false){put('pf-performance','Some token prices unavailable');return;}
  remember(total);
  if(!samples.length||samples[samples.length-1]!==total){
    samples.push(total);if(samples.length>24)samples.shift();
  }
  spark();
  if(samples.length>1){
    var first=samples[0],diff=total-first;
    put('pf-performance',Math.abs(diff)<0.005?'':(diff>=0?'+':'−')+money(Math.abs(diff))+' this session');
  }else put('pf-performance','');
}
document.addEventListener('orca:portfolio-value',paint);
function boot(){
  var cached=recalled();
  if(cached!=null){
    put('pf-total',money(cached));
    samples=[cached];
    spark();
    put('pf-performance','Refreshing…');
    setTimeout(function(){if(window.__orcaPortfolioValue==null)put('pf-performance','Last confirmed balance')},12000);
  }

}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
