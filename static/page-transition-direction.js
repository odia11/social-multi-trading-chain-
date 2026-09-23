/* Sets the direction app-ux.css's mobile view-transition rules need (forward
   vs back) before each cross-document view transition starts, using the
   Navigation API -- Chromium-only today, which is exactly this app's mobile
   target (Android Chrome). Anywhere else this is simply a no-op: navigation
   proceeds exactly as it always has, with no CSS-driven slide.

   A separate, non-deferred file rather than folded into app-ux.js: it has to
   run before the Navigation API's pagereveal event can fire, which can be
   earlier than a deferred script executes.

   `pagereveal` fires on the page being navigated TO, right as it is
   revealed; `event.viewTransition` exists only when the browser is actually
   running a cross-document transition for this navigation, so everything
   here is skipped on a plain reload, a cross-origin navigation, or a first
   load with nothing to compare against. */
(function(){
'use strict';
if(!('navigation' in window)) return;

window.addEventListener('pagereveal', function(event){
  if(!event.viewTransition) return;
  try{
    var activation = window.navigation.activation;
    if(!activation || activation.navigationType !== 'traverse' || !activation.from) return;
    // A back-swipe, the browser's own back control, or history.back() all
    // land here as navigationType 'traverse' -- direction is which way the
    // session history index moved, not which button/gesture caused it.
    var direction = activation.entry.index < activation.from.index ? 'back' : 'forward';
    document.documentElement.setAttribute('data-vt-direction', direction);
  }catch(_){ }
});
})();
