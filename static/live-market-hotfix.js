/* Live Market compatibility layer: Buy/Sell switching + mobile search only.
   The visible chart is owned by the gold chart engine. */
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
  var s=document.createElement('style');
  s.id='oa-live-authoritative-fix';
  s.textContent='\
body.oa-live-v2 .pt-chart-svg{opacity:0!important;pointer-events:none!important}\
body.oa-live-v2 .pt-chart-axis{display:none!important}\
body.oa-live-v2 .pt-price-pill{display:none!important}\
@media(max-width:767px){\
 body.oa-live-v2 .pt-search{min-height:50px!important;border-radius:14px!important;font-size:14px!important}\
 body.oa-live-v2 .pt-nb-search{height:44px!important;min-height:44px!important;font-size:16px!important;border-radius:12px!important;padding:0 42px 0 36px!important}\
 body.oa-search-open{overflow:hidden!important}\
 body.oa-search-open .pt-nb-topbar{position:fixed!important;top:0!important;left:0!important;right:0!important;width:100%!important;max-width:none!important;height:100dvh!important;min-height:100dvh!important;margin:0!important;padding:0!important;display:block!important;background:#080d12!important;z-index:1400!important;overflow:visible!important}\
 body.oa-search-open .pt-nb-topbar>.pt-nb-logo,\
 body.oa-search-open .pt-nb-topbar>.pt-nb-menu-btn,\
 body.oa-search-open .pt-nb-topbar>.pt-nb-nav,\
 body.oa-search-open .pt-nb-topbar>.pt-nb-right,\
 body.oa-search-open .pt-nb-topbar>.pt-nb-more-wrap{display:none!important}\
 body.oa-search-open .pt-nb-search-wrap.mobile-search-open{position:fixed!important;top:0!important;left:0!important;right:0!important;bottom:auto!important;width:100%!important;max-width:none!important;height:auto!important;min-height:calc(env(safe-area-inset-top,0px) + 76px)!important;margin:0!important;padding:calc(env(safe-area-inset-top,0px) + 12px) 14px 12px!important;background:#080d12!important;display:grid!important;grid-template-columns:minmax(0,1fr) 48px!important;grid-template-rows:48px auto!important;column-gap:10px!important;row-gap:10px!important;align-items:center!important;z-index:1450!important;overflow:visible!important;box-sizing:border-box!important;border-bottom:1px solid #18232d!important}\
 body.oa-search-open .pt-nb-search-wrap.mobile-search-open .pt-nb-search{position:relative!important;grid-column:1!important;grid-row:1!important;width:100%!important;max-width:none!important;height:48px!important;min-height:48px!important;margin:0!important;padding:0 16px!important;border:1px solid #263746!important;border-radius:14px!important;background:#0b151f!important;color:#eef1f5!important;font-size:17px!important;line-height:48px!important;box-shadow:none!important;outline:none!important;appearance:none!important;-webkit-appearance:none!important}\
 body.oa-search-open .pt-nb-search-wrap.mobile-search-open .pt-nb-search::-webkit-search-cancel-button{display:none!important;-webkit-appearance:none!important}\
 body.oa-search-open .pt-nb-search-wrap.mobile-search-open .pt-nb-search-icon{display:none!important}\
 body.oa-search-open .pt-nb-search-wrap.mobile-search-open .pt-nb-search-close{display:flex!important;position:relative!important;grid-column:2!important;grid-row:1!important;align-items:center!important;justify-content:center!important;width:48px!important;height:48px!important;min-width:48px!important;min-height:48px!important;margin:0!important;padding:0!important;border:1px solid #263746!important;border-radius:14px!important;background:#0b151f!important;color:#eef1f5!important;font-size:30px!important;font-weight:400!important;line-height:1!important;box-sizing:border-box!important}\
 body.oa-search-open .pt-nb-search-wrap.mobile-search-open .pt-nb-search-results{display:none;grid-column:1/-1!important;grid-row:2!important;position:relative!important;top:auto!important;left:auto!important;right:auto!important;width:100%!important;max-height:calc(100dvh - env(safe-area-inset-top,0px) - 92px)!important;margin:0!important;border:1px solid #212c37!important;border-top:2px solid #f7b955!important;border-radius:14px!important;background:#0b151f!important;overflow-y:auto!important;box-shadow:0 18px 42px rgba(0,0,0,.42)!important}\
 body.oa-search-open .pt-nb-search-wrap.mobile-search-open .pt-nb-search-results.open{display:block!important}\
}\
';
  document.head.appendChild(s)
}
function boot(){installFixStyles();installModeObserver()}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
