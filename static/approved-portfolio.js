/* Real OrcAgent balances only. Never invent token rows, returns, or 24h PnL. */
(function(){
'use strict';
if((location.pathname.replace(/\/+$/,'')||'/')!=='/wallet')return;
var samples=[];
var STORAGE_KEY='orcaPortfolioLastConfirmedTotal';
function remember(total){try{sessionStorage.setItem(STORAGE_KEY,String(total))}catch(e){}}
function recalled(){try{var n=Number(sessionStorage.getItem(STORAGE_KEY));return Number.isFinite(n)&&n>=0?n:null}catch(e){return null}}
function money(n){
  n=Number(n);
  return Number.isFinite(n)?'$'+n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
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
  var d=value&&value.detail||{},total=Number(d.total);
  if(!Number.isFinite(total)||total<0)return;
  put('pf-total',money(total));
  remember(total);
  if(d.stable!=null)put('pf-usdc-asset',money(d.stable));
  if(d.sol!=null)put('pf-sol-asset',money(d.sol));
  if(!samples.length||samples[samples.length-1]!==total){
    samples.push(total);if(samples.length>24)samples.shift();
  }
  spark();
  if(samples.length>1){
    var first=samples[0],diff=total-first;
    put('pf-performance','Session '+(diff>=0?'+':'−')+money(Math.abs(diff))+' · live balance');
  }else put('pf-performance','Live multi-chain balance');
}
document.addEventListener('orca:portfolio-value',paint);
function boot(){
  var cached=recalled();
  if(cached!=null){
    put('pf-total',money(cached));
    samples=[cached];
    spark();
    put('pf-performance','Refreshing live multi-chain balance…');
  }
  /* On a first-ever session there is no confirmed total to reuse. As soon as
     the fast pooled-USDC read lands, use it as an honest provisional floor
     while the complete token + SOL snapshot finishes. */
  var avail=document.getElementById('avail');
  function provisionalFromAvail(){
    var totalEl=document.getElementById('pf-total');
    if(!avail||!totalEl||totalEl.textContent.trim()!=='—')return;
    var n=Number((avail.textContent||'').replace(/[^0-9.\-]/g,''));
    if(Number.isFinite(n)&&n>=0){
      put('pf-total',money(n));samples=[n];spark();
      put('pf-performance','Syncing complete multi-chain balance…');
    }
  }
  provisionalFromAvail();
  if(avail&&window.MutationObserver)new MutationObserver(provisionalFromAvail).observe(avail,{childList:true,characterData:true,subtree:true});
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
