/* Adds the oa-native-mobile-scroll class that app_performance.py's
   accompanying <style> block (still inline -- CSS is unaffected, see below)
   targets to give every ordinary mobile document page the same single
   standards-mode root scroller Android Chrome and iOS Safari both need.

   A plain external <script src>, not an inline block, because this file is
   injected by app_performance.py's after_request hook, which runs BEFORE
   security_hardening.py's nonce-injection pass in the actual per-request
   execution order (Flask calls after_request hooks in reverse install()
   order -- see app_entry.py). An inline <script> appended here would never
   get CSP's per-response nonce and script-src-elem would silently drop it,
   meaning the oa-native-mobile-scroll class was never actually applied on
   any page -- confirmed via a live CSP-enforced console check. A same-
   origin src= script is covered by CSP's 'self' source expression instead,
   independent of the nonce, so it always runs. The sibling <style> tag
   this pairs with was never affected: CSP's style-src here still allows
   'unsafe-inline', so only script elements needed this fix. See
   page-transition-direction.js for the same fix applied to a third script.

   Not deferred: this mirrors the exact position/timing of the inline block
   it replaces (right after </head>, before <body> parses) -- the class has
   to land before the page's own content paints, or Android briefly renders
   with the wrong scroll owner and the layout visibly jumps/locks once this
   script finally ran. */
(function(){
'use strict';
if(window.matchMedia && window.matchMedia('(max-width:768px)').matches){
  document.documentElement.classList.add('oa-native-mobile-scroll');
}
})();
