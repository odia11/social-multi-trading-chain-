/* OrcAgent Live Market deep-link reliability fix.
   Ensures /live-market?addr=<mint> lands on the exact token in the CURRENT
   Live Market poster-card flow. The Live Market no longer uses the old
   showTokenCard() modal as its primary navigation path; _lmJumpToCard(mint)
   is the canonical resolver used by rows, leaders, featured tokens and search.
*/
(function(){
'use strict';
var params=new URLSearchParams(window.location.search||'');
var mint=(params.get('addr')||'').trim();
if(!mint)return;

var done=false;
var busy=false;
var tries=0;
var timer=null;

function targetExists(){
  try{
    return !!document.querySelector('.lm-poster-card[data-mint="'+CSS.escape(mint)+'"]');
  }catch(e){
    return false;
  }
}

async function tryOpen(){
  if(done||busy)return done;
  tries++;
  if(typeof window._lmJumpToCard!=='function')return false;
  busy=true;
  try{
    var ok=await window._lmJumpToCard(mint);
    if(ok||targetExists()){
      done=true;
      if(timer){clearInterval(timer);timer=null;}
      /* Keep the addr in the URL so refresh/back-forward can restore the same
         token, but ensure the matching card is centered again after layout. */
      setTimeout(function(){
        var card=null;
        try{card=document.querySelector('.lm-poster-card[data-mint="'+CSS.escape(mint)+'"]');}catch(e){}
        if(card)card.scrollIntoView({behavior:'auto',block:'center'});
      },80);
      return true;
    }
  }catch(e){
    console.error('[live-market deeplink] exact-token open failed',e);
  }finally{
    busy=false;
  }
  return false;
}

function begin(){
  tryOpen();
  timer=setInterval(function(){
    if(done||tries>=80){clearInterval(timer);timer=null;return;}
    tryOpen();
  },250);
  window.addEventListener('load',tryOpen,{once:true});
  window.addEventListener('pageshow',tryOpen);
  document.addEventListener('visibilitychange',function(){if(!document.hidden)tryOpen();});
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',begin,{once:true});else begin();
})();
