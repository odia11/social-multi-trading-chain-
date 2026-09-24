/* OrcAgent Home Start Trading route guard.
 * Home's hero is rebuilt by responsive JS and older iOS/PWA caches can still
 * execute a previous home bundle whose CTA pointed at Live Market. This file
 * owns that one navigation intent at the DOM boundary: every Home navigation
 * CTA labelled Start Trading always opens the autonomous bot overview.
 */
(function(){
'use strict';
var here=location.pathname.replace(/\/+$/,'')||'/';
if(here!=='/')return;
var TARGET='/auto-trading-bot';

function label(el){
  return String((el&&el.textContent)||'').replace(/\s+/g,' ').trim().toLowerCase();
}
function isStartTradingNav(el){
  if(!el)return false;
  if(el.id==='bot-toggle-btn'||el.id==='sb-start-btn')return false;
  if(el.id==='bot-start-landing'||el.id==='oa-home-bot-btn')return true;
  if(el.classList&&(
      el.classList.contains('oa-home-primary')||
      el.classList.contains('oa-m-primary')||
      el.classList.contains('hero-cta')))return true;
  var txt=label(el);
  return txt==='start trading'||txt.indexOf('start trading →')===0||txt.indexOf('start trading ➜')===0;
}
function normalize(root){
  var scope=root&&root.querySelectorAll?root:document;
  var selectors='a.oa-home-primary,a.oa-m-primary,a.hero-cta,#bot-start-landing,#oa-home-bot-btn';
  scope.querySelectorAll(selectors).forEach(function(el){
    if(!isStartTradingNav(el))return;
    if(el.tagName==='A')el.setAttribute('href',TARGET);
    el.removeAttribute('onclick');
    el.dataset.oaAutoBotRoute='1';
  });
}
function intercept(e){
  var node=e.target&&e.target.closest?e.target.closest('a,button'):null;
  if(!isStartTradingNav(node))return;
  if(e.cancelable)e.preventDefault();
  e.stopPropagation();
  if(e.stopImmediatePropagation)e.stopImmediatePropagation();
  if(node&&node.tagName==='A')node.setAttribute('href',TARGET);
  window.location.assign(TARGET);
}

/* Capture before any old Home bundle gets the event. Click only: this used
   to also listen to pointerdown and touchstart ({passive:false}) on window.
   A non-passive window touchstart makes Android Chrome wait for JS on EVERY
   touch anywhere on Home before it may scroll, and passive:false also opts
   out of Chrome's own "window touch listeners are passive" intervention --
   so Home scrolled late and jerkily or not at all under load. It also
   navigated away the moment a scroll merely started on the CTA. A tap still
   produces a click, and a capture-phase window click listener still runs
   before any handler an old bundle put on the button itself. */
window.addEventListener('click',intercept,true);

function boot(){
  normalize(document);
  try{
    new MutationObserver(function(mutations){
      mutations.forEach(function(m){
        m.addedNodes.forEach(function(n){
          if(n.nodeType!==1)return;
          if(n.matches&&isStartTradingNav(n)){
            if(n.tagName==='A')n.setAttribute('href',TARGET);
            n.removeAttribute('onclick');
          }
          normalize(n);
        });
      });
    }).observe(document.documentElement,{childList:true,subtree:true});
  }catch(_){ }
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
