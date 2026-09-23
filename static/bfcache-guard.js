/* Normalizes the browser's bfcache (back/forward cache) restore into one
   custom event, orca:bfcache-restored, that any page-specific script can
   listen for to re-sync live data (balances, feeds, prices) without a full
   reload -- restoring a document from bfcache does not re-run its scripts,
   it just fires pageshow with event.persisted=true on the already-loaded
   page, so state that went stale while the tab was cached needs an explicit
   nudge to refresh.

   A plain external <script src>, not an inline block, because this file is
   injected by app_performance.py's after_request hook, which runs BEFORE
   security_hardening.py's nonce-injection pass in the actual per-request
   execution order (Flask calls after_request hooks in reverse install()
   order -- see app_entry.py). An inline <script> appended here would never
   get CSP's per-response nonce and script-src-elem would silently drop it.
   A same-origin src= script is covered by CSP's 'self' source expression
   instead, independent of the nonce, so it always runs. See
   page-transition-direction.js for the same fix applied to a second script.

   Not deferred: this mirrors the exact position/timing of the inline block
   it replaces (right after </head>, before <body> parses), so pageshow
   listener registration on the very first load is not pushed any later
   than it already was. */
(function(){
'use strict';
window.addEventListener('pageshow', function(e){
  if(!e.persisted) return;
  e.stopImmediatePropagation();
  setTimeout(function(){
    document.dispatchEvent(new CustomEvent('orca:bfcache-restored'));
  }, 0);
}, true);
})();
