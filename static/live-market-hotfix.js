/* Live Market production compatibility layer.
   IMPORTANT: charts are owned exclusively by live-market-pro.js. That engine
   already owns the batched live-price ticker and touch scrub interaction.
   This file only restores its visibility after the redesign and keeps the
   Buy/Sell mode switch + mobile search presentation consistent. */
(function(){
'use strict';
if((location.pathname.replace(/\/+$/,'')||'/')!=='/live-market')return;

function cleanSymbol(s){return String(s||'').replace(/^\$/,'').trim().toUpperCase()}
function currentCard(){var se=document.getElementById('pt-sheet-sym'),sym=cleanSymbol(se&&se.textContent);if(!sym)return null;var cards=document.querySelectorAll('.pt-card');for(var i=0;i<cards.length;i++){var x=cards[i].querySelector('.pt-tok-sym');if(cleanSymbol(x&&x.textContent).indexOf(sym)===0)return cards[i]}return null}
function switchTradeMode(mode){var card=currentCard();if(!card)return false;var btn=card.querySelector(mode==='sell'?'[data-action="sell"]':'[data-action="buy-open"]');if(!btn)return false;btn.click();return true}
document.addEventListener('click',function(e){var b=e.target.closest('.oa-swipe-mode [data-mode]');if(!b)return;e.preventDefault();e.stopImmediatePropagation();switchTradeMode(b.dataset.mode)},true);
function syncModeButtons(){var sheet=document.getElementById('pt-sheet');if(!sheet)return;var sell=sheet.classList.contains('sell-mode');sheet.querySelectorAll('.oa-swipe-mode [data-mode]').forEach(function(b){var on=(b.dataset.mode==='sell')===sell;b.classList.toggle('active',on);b.setAttribute('aria-pressed',on?'true':'false')})}
function installModeObserver(){var sheet=document.getElementById('pt-sheet');if(!sheet)return;syncModeButtons();new MutationObserver(syncModeButtons).observe(sheet,{attributes:true,attributeFilter:['class']})}

function installFixStyles(){
  if(document.getElementById('oa-live-authoritative-fix'))return;
  var s=document.createElement('style');s.id='oa-live-authoritative-fix';s.textContent='\
body.oa-live-v2 .pt-chart-svg{opacity:1!important;pointer-events:auto!important;display:block!important;touch-action:pan-y!important}\
body.oa-live-v2 .pt-chart-axis{display:flex!important}\
body.oa-live-v2 .pt-price-pill{display:block!important}\
body.oa-live-v2 .pt-chart-svg line[stroke="#3ad29b"]{stroke:#f7b955!important}\
body.oa-live-v2 .pt-chart-svg rect[fill="#3ad29b"]{fill:#f7b955!important}\
body.oa-live-v2 .pt-chart-scrub-line[style*="display: block"]{display:block!important}\
body.oa-live-v2 .pt-chart-scrub-dot[style*="display: block"]{display:block!important}\
body.oa-live-v2 .pt-chart-scrub-tip[style*="display: block"]{display:block!important}\
body.oa-live-v2 .oa-goldline-svg,body.oa-live-v2 .oa-chart-hotfix,body.oa-live-v2 .oa-goldline-status,body.oa-live-v2 .oa-chart-hotfix-status{display:none!important}\
@media(max-width:767px){\
 body.oa-live-v2 .pt-search{min-height:50px!important;border-radius:14px!important;font-size:14px!important}\
 body.oa-live-v2 .pt-nb-search{height:44px!important;min-height:44px!important;font-size:16px!important;border-radius:12px!important;padding:0 42px 0 36px!important}\
 body.oa-live-v2 .pt-nb-search-wrap.mobile-search-open{position:fixed!important;inset:0!important;z-index:1200!important;max-width:none!important;width:auto!important;margin:0!important;padding:calc(env(safe-area-inset-top,0px) + 12px) 14px 14px!important;background:#06101a!important;display:grid!important;grid-template-columns:minmax(0,1fr) 44px!important;grid-template-rows:48px auto!important;gap:10px!important;align-items:center!important}\
 body.oa-live-v2 .pt-nb-search-wrap.mobile-search-open .pt-nb-search{grid-column:1!important;grid-row:1!important;width:100%!important;height:48px!important;min-height:48px!important;margin:0!important;padding:0 16px 0 42px!important;border:1px solid #263746!important;border-radius:14px!important;background:#0a141e!important;color:#eef1f5!important;box-shadow:none!important}\
 body.oa-live-v2 .pt-nb-search-wrap.mobile-search-open .pt-nb-search-icon{display:block!important;position:absolute!important;left:28px!important;top:calc(env(safe-area-inset-top,0px) + 36px)!important;transform:translateY(-50%)!important;z-index:2!important}\
 body.oa-live-v2 .pt-nb-search-wrap.mobile-search-open .pt-nb-search-close{display:flex!important;grid-column:2!important;grid-row:1!important;align-items:center!important;justify-content:center!important;width:44px!important;height:44px!important;min-width:44px!important;min-height:44px!important;margin:0!important;padding:0!important;border:1px solid #263746!important;border-radius:13px!important;background:#0a141e!important;color:#eef1f5!important;font-size:28px!important;line-height:1!important}\
 body.oa-live-v2 .pt-nb-search-wrap.mobile-search-open .pt-nb-search-results{grid-column:1/-1!important;grid-row:2!important;position:relative!important;top:auto!important;left:auto!important;right:auto!important;width:100%!important;max-height:calc(100dvh - 92px - env(safe-area-inset-top,0px))!important;margin:0!important;border-radius:14px!important}\
}\
';document.head.appendChild(s);
}
function cleanupDuplicateCharts(){document.querySelectorAll('.oa-goldline-svg,.oa-chart-hotfix,.oa-goldline-status,.oa-chart-hotfix-status').forEach(function(n){n.remove()})}
function boot(){installFixStyles();installModeObserver();cleanupDuplicateCharts();new MutationObserver(cleanupDuplicateCharts).observe(document.body,{childList:true,subtree:true})}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
