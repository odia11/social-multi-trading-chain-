/* OrcAgent Live Market deep-link reliability fix.
   Ensures /live-market?addr=<mint> always opens the exact token after the
   Live Market scripts and token modal are ready, including slower iOS/Phantom
   page loads where the old inline handler could race showTokenCard(). */
(function(){
'use strict';
var params=new URLSearchParams(window.location.search||'');
var mint=(params.get('addr')||'').trim();
if(!mint)return;

var opened=false;
var tries=0;
function tryOpen(){
  if(opened)return true;
  tries++;
  if(typeof window.showTokenCard!=='function')return false;
  var modal=document.getElementById('lm-token-modal');
  var body=document.getElementById('lm-modal-body');
  if(!modal||!body)return false;
  opened=true;
  try{
    window.showTokenCard('',mint);
    return true;
  }catch(e){
    opened=false;
    return false;
  }
}

function begin(){
  if(tryOpen())return;
  var timer=setInterval(function(){
    if(tryOpen()||tries>=120)clearInterval(timer);
  },100);
  window.addEventListener('load',tryOpen,{once:true});
  window.addEventListener('pageshow',tryOpen);
  document.addEventListener('visibilitychange',function(){if(!document.hidden)tryOpen();});
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',begin,{once:true});else begin();
})();
