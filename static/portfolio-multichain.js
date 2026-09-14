/* Multi-chain Portfolio presentation/safety layer. */
(function(){
'use strict';
if((location.pathname.replace(/\/+$/,'')||'/')!=='/wallet') return;

var LABELS={bsc:'BSC',base:'BASE',arbitrum:'ARB',polygon:'POLY',robinhood:'HOOD',solana:'SOL'};

function list(){ return window._wTokens||window._allSpl||[]; }
function indexFromButton(btn){
  var m=(btn.getAttribute('onclick')||'').match(/_toggleTokTrade\((\d+)\)/);
  return m?Number(m[1]):-1;
}
function decorate(){
  var rows=document.querySelectorAll('.tok-row-block');
  rows.forEach(function(block){
    var btn=block.querySelector('.tok-trade-btn');
    if(!btn) return;
    var i=indexFromButton(btn), t=list()[i];
    if(!t) return;
    var chain=String(t.chain||'solana').toLowerCase();
    if(chain==='solana') return;
    block.dataset.chain=chain;
    var name=block.querySelector('.tok-name');
    if(name && !name.querySelector('.oa-chain-badge')){
      var badge=document.createElement('span');
      badge.className='oa-chain-badge';
      badge.textContent=LABELS[chain]||chain.toUpperCase();
      name.appendChild(badge);
    }
    // The old per-row swap control is Solana-only. Never let an EVM holding
    // accidentally enter that path; route trading back to Live Market where
    // chain-aware buy/sell execution already exists.
    btn.title='Trade on '+(LABELS[chain]||chain);
    btn.setAttribute('aria-label',btn.title);
  });
}

document.addEventListener('click',function(e){
  var btn=e.target.closest('.tok-trade-btn');
  if(!btn) return;
  var i=indexFromButton(btn), t=list()[i];
  if(!t) return;
  var chain=String(t.chain||'solana').toLowerCase();
  if(chain==='solana') return;
  e.preventDefault(); e.stopPropagation(); if(e.stopImmediatePropagation)e.stopImmediatePropagation();
  var addr=t.token_address||t.address||t.mint||'';
  window.location.href='/live-market?mint='+encodeURIComponent(addr)+'&chain='+encodeURIComponent(chain);
},true);

var style=document.createElement('style');
style.textContent='.oa-chain-badge{display:inline-flex;align-items:center;margin-left:7px;padding:2px 6px;border:1px solid rgba(247,185,85,.28);border-radius:999px;color:#f7b955;background:rgba(247,185,85,.08);font-size:9px;font-weight:800;letter-spacing:.06em;vertical-align:middle}.tok-row-block[data-chain="robinhood"] .oa-chain-badge{color:#d9b7ff;border-color:rgba(217,183,255,.28);background:rgba(217,183,255,.08)}';
document.head.appendChild(style);

function boot(){
  decorate();
  var h=document.querySelector('.holdings');
  if(h&&window.MutationObserver){
    var timer=null;
    new MutationObserver(function(){clearTimeout(timer);timer=setTimeout(decorate,0);}).observe(h,{childList:true,subtree:true});
  }
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
