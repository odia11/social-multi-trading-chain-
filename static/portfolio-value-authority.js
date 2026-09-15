/* Keep the visible Portfolio total authoritative and prevent legacy stable-only
   observers from overwriting it after the multi-chain value has been painted. */
(function(){
'use strict';
if((location.pathname.replace(/\/+$/,'')||'/')!=='/wallet')return;
var authoritative=null,repairing=false,observer=null;
function money(v){var n=Number(v||0);if(!isFinite(n)||n<0)n=0;return '$'+n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});}
function totalEl(){return document.getElementById('pf-total');}
function paint(){
  var el=totalEl();
  if(!el||authoritative==null)return;
  var wanted=money(authoritative);
  if(el.textContent===wanted)return;
  repairing=true;
  el.textContent=wanted;
  repairing=false;
}
function bind(){
  var el=totalEl();
  if(!el)return false;
  if(observer)observer.disconnect();
  observer=new MutationObserver(function(){if(!repairing)paint();});
  observer.observe(el,{childList:true,characterData:true,subtree:true});
  return true;
}
document.addEventListener('orca:portfolio-value',function(e){
  var n=Number(e&&e.detail&&e.detail.total);
  if(!isFinite(n)||n<0)return;
  authoritative=n;
  if(!observer)bind();
  paint();
});
function boot(){
  if(!bind())setTimeout(boot,80);
  /* Ask the multi-chain layer for one authoritative paint after all portfolio
     presentation scripts have initialised. */
  setTimeout(function(){if(typeof window.OrcAgentRefreshPortfolioValue==='function')window.OrcAgentRefreshPortfolioValue();},120);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
