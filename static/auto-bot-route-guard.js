/* Captures every tap/click on a "Start Trading" CTA, anywhere in the app,
   and forces it to the dedicated Auto Trading Bot route (/auto-trading-bot)
   even if an old cached home-mobile/home-desktop bundle still points that
   CTA at /live-market. Capture phase and injected as early in <head> as
   possible on purpose: it has to win over navbar.js/home-mobile.js's own
   handlers regardless of which bundle version the client has cached.

   A plain external <script src>, not an inline block, because this file is
   injected by auto_trading_bot_route.py's after_request hook, which
   installs BEFORE security_hardening.py in app_entry.py's install() order.
   Flask runs after_request hooks in REVERSE install() order, so this
   hook's inline script used to be appended to the response body AFTER
   security_hardening.py's CSP nonce-injection pass already ran -- it never
   got a nonce and CSP silently dropped the whole guard, meaning "Start
   Trading" taps on a stale cached bundle silently fell through to whatever
   the old anchor's href already pointed at. A same-origin src= script is
   covered by CSP's 'self' source expression instead, independent of the
   nonce, so it always runs. See static/page-transition-direction.js for
   the same fix applied to a first instance of this bug.

   Not deferred: this mirrors the exact position/timing of the inline block
   it replaces (right after <head>, before any other script), which is what
   lets its capture-phase listener register ahead of navbar.js/home-mobile.js's
   own listeners on every page. */
(function(){
'use strict';
var TARGET = '/auto-trading-bot';
function label(el){ return String((el && el.textContent) || '').replace(/\s+/g, ' ').trim().toLowerCase(); }
function isBotToggle(el){
  return !!(el && (el.id === 'bot-toggle-btn' || el.id === 'sb-start-btn' ||
    (el.closest && el.closest('#bot-dashboard,.status-card'))));
}
function isStartNavigation(el){
  if(!el || isBotToggle(el)) return false;
  if(el.id === 'bot-start-landing' || el.id === 'oa-home-bot-btn' || el.id === 'mn-drawer-trade-btn') return true;
  if(el.classList && (el.classList.contains('oa-home-primary') ||
     el.classList.contains('oa-m-primary') || el.classList.contains('hero-cta'))) return true;
  var t = label(el);
  return t === 'start trading' || t.indexOf('start trading →') === 0 || t.indexOf('start trading ➜') === 0;
}
document.addEventListener('click', function(e){
  var el = e.target && e.target.closest ? e.target.closest('a,button') : null;
  if(!isStartNavigation(el)) return;
  e.preventDefault();
  e.stopPropagation();
  if(e.stopImmediatePropagation) e.stopImmediatePropagation();
  window.location.href = TARGET;
}, true);
// Click only. A touchend listener used to navigate here too, but touchend
// also fires at the end of a SCROLL whose finger happened to start on the
// CTA -- so trying to scroll Home past the hero's big "Start Trading"
// button sent people to the bot page instead. A real tap always produces a
// click, which the capture-phase listener above already owns.
})();
