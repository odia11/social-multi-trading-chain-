/* Real OrcAgent balances only. Never invent token rows, returns, or 24h PnL. */
(function(){
'use strict';
if((location.pathname.replace(/\/+$/,'')||'/')!=='/wallet')return;
var samples=[];
function money(n){
  n=Number(n);
  return Number.isFinite(n)?'$'+n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
}
function put(id,value){var e=document.getElementById(id);if(e)e.textContent=value}
function spark(){
  var line=document.getElementById('pf-spark-line'),fill=document.getElementById('pf-spark-fill');
  if(!line||!fill||samples.length<2)return;
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
})();
