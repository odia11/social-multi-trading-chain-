/* Portfolio asset actions for /wallet.
   Reuses the existing wallet swap modal/quote/execute flow. */
(function(){
'use strict';
if(location.pathname.replace(/\/+$/,'')!=='/wallet') return;

function tokenForButton(btn){
  var raw=btn.getAttribute('onclick')||'';
  var m=raw.match(/_toggleTokTrade\((\d+)\)/);
  if(!m) return null;
  var i=Number(m[1]);
  var list=window._wTokens||window._allSpl||[];
  var t=list[i];
  if(!t) return null;
  return {index:i,token:t};
}
function tokenMint(t){
  return t && (t.mint||t.address||t.token_address||t.tokenAddress||'');
}
function polishButtons(root){
  (root||document).querySelectorAll('.tok-trade-btn').forEach(function(btn){
    btn.title='Swap';
    btn.setAttribute('aria-label','Swap asset');
  });
}
function openAssetSwap(btn){
  var hit=tokenForButton(btn);
  if(!hit){
    var raw=btn.getAttribute('onclick')||'';
    var m=raw.match(/_toggleTokTrade\((\d+)\)/);
    if(m && typeof window._toggleTokTrade==='function') window._toggleTokTrade(Number(m[1]));
    return;
  }
  var mint=tokenMint(hit.token);
  if(!mint || typeof window.openSwapModal!=='function'){
    if(typeof window._toggleTokTrade==='function') window._toggleTokTrade(hit.index);
    return;
  }
  /* Existing modal opens SOL -> selected token. Flip immediately so the
     asset the user tapped becomes FROM while keeping the tested quote and
     execution code untouched. */
  window.openSwapModal(mint);
  setTimeout(function(){
    if(typeof window._swFlip==='function') window._swFlip();
  },0);
}
function boot(){
  var holdings=document.querySelector('.holdings');
  if(!holdings) return;
  polishButtons(holdings);
  holdings.addEventListener('click',function(e){
    var btn=e.target.closest('.tok-trade-btn');
    if(!btn || !holdings.contains(btn)) return;
    e.preventDefault();
    e.stopPropagation();
    if(e.stopImmediatePropagation) e.stopImmediatePropagation();
    openAssetSwap(btn);
  },true);
  if(window.MutationObserver){
    var timer=null;
    new MutationObserver(function(){
      clearTimeout(timer);
      timer=setTimeout(function(){polishButtons(holdings);},0);
    }).observe(holdings,{childList:true,subtree:true});
  }
}
if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot); else boot();
})();
