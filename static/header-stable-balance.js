/* Show the user's aggregate stablecoin spending balance in the shared top bar. */
(function(){
'use strict';
var timer=null,inFlight=false,last='';

function el(){return document.getElementById('pt-nb-sol-balance')}
function render(value){
  var node=el();
  if(!node)return;
  node.textContent=value||'$0.00';
  node.setAttribute('aria-label','Available stablecoin balance '+(value||'$0.00'));
  var pill=node.closest('.pt-nb-balance,.pt-nb-sol,.pt-nb-wallet-balance')||node.parentElement;
  if(pill) pill.title='Available stablecoin balance across OrcAgent chains';
}
function refresh(force){
  if(inFlight||!el())return Promise.resolve();
  inFlight=true;
  var url='/api/header/stable-balance'+(force?'?t='+Date.now():'');
  return fetch(url,{credentials:'include',cache:'no-store'})
    .then(function(r){if(!r.ok)throw new Error('balance unavailable');return r.json()})
    .then(function(d){
      if(!d||!d.ok)return;
      var text=d.formatted||('$'+Number(d.total_usd||0).toFixed(2));
      last=text;render(text);
    })
    .catch(function(){if(last)render(last)})
    .finally(function(){inFlight=false});
}
function start(){
  if(!el())return;
  render('$0.00');
  refresh(true);
  setTimeout(function(){refresh(true)},500); // wins any later /api/me SOL paint
  if(timer)clearInterval(timer);
  timer=setInterval(function(){refresh(false)},20000);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
window.addEventListener('pageshow',function(){refresh(true)});
window.addEventListener('focus',function(){refresh(true)});
document.addEventListener('visibilitychange',function(){if(!document.hidden)refresh(true)});
window.OrcAgentRefreshStableBalance=function(){return refresh(true)};
})();
