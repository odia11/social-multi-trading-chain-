/* Edge swipe-to-go-back, the way native apps behave: a drag starting at the
   very left edge of the screen and moving right takes you to the previous
   page, like iOS's edge-swipe or Android's system back gesture. Chrome on
   Android does not give a page this for free the way a native app gets it
   from the OS, so it is built here instead.

   Same intent-detection convention already used for chart scrubbing and the
   Live Market buy/sell swipe (Math.abs(dx) > Math.abs(dy) * 1.15): nothing is
   ever preventDefault()'d until a clearly horizontal drag is confirmed, so an
   ordinary vertical scroll that happens to start near the left edge is never
   hijacked -- only a drag that is unmistakably "swipe right" is.

   This is a classic multi-page app (every navigation is a real page load),
   so there is no client-side route to animate to -- the gesture drives a
   small edge indicator during the drag and then calls history.back() on
   release past the threshold, mirroring the existing .mobile-back-btn
   fallback (nothing to go back to -> Home) instead of navigating nowhere. */
(function(){
'use strict';
if(!('ontouchstart' in window)) return;

var EDGE_ZONE   = 24;   // px from the left edge a drag must start within
var THRESHOLD   = 70;   // px of rightward drag that commits the navigation
var MAX_PULL    = 120;  // px at which the indicator reaches full strength

var el = null;
function indicator(){
  if(el) return el;
  el = document.createElement('div');
  el.id = 'oa-swipe-back-indicator';
  el.setAttribute('aria-hidden', 'true');
  el.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>';
  el.style.cssText = 'position:fixed;top:50%;left:0;z-index:2000;width:40px;height:40px;'
    + 'margin-top:-20px;border-radius:0 999px 999px 0;background:rgba(18,22,28,.92);'
    + 'color:#f7b955;display:flex;align-items:center;justify-content:center;'
    + 'transform:translateX(-100%);opacity:0;pointer-events:none;'
    + 'transition:transform .18s ease,opacity .18s ease;will-change:transform,opacity';
  document.body.appendChild(el);
  return el;
}

function setPull(px, animated){
  var ind = indicator();
  var pct = Math.max(0, Math.min(1, px / MAX_PULL));
  ind.style.transition = animated ? 'transform .18s ease,opacity .18s ease' : 'none';
  ind.style.transform  = 'translateX(' + (-100 + pct * 100) + '%)';
  ind.style.opacity    = String(pct);
}

function resetPull(){ setPull(0, true); }

function goBack(){
  if(window.history.length > 1) window.history.back();
  else if(location.pathname !== '/') location.href = '/';
}

function blockedByOverlay(){
  var html = document.documentElement;
  return html.classList.contains('oa-modal-open')
    || html.classList.contains('oa-wallet-actions-open')
    || html.classList.contains('oa-app-menu-open')
    || html.classList.contains('oa-search-open');
}

var startX = 0, startY = 0, tracking = false, intent = null;

document.addEventListener('touchstart', function(e){
  tracking = false; intent = null;
  if(e.touches.length !== 1) return;
  if(blockedByOverlay()) return;
  var t = e.touches[0];
  if(t.clientX > EDGE_ZONE) return;
  var active = document.activeElement;
  if(active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.isContentEditable)) return;
  if(e.target.closest && e.target.closest('.oa-swipe-mode,[data-no-swipe-back]')) return;
  startX = t.clientX; startY = t.clientY; tracking = true;
}, {passive: true});

document.addEventListener('touchmove', function(e){
  if(!tracking || e.touches.length !== 1) return;
  var t = e.touches[0];
  var dx = t.clientX - startX, dy = t.clientY - startY;
  if(intent === null){
    if(Math.abs(dx) < 10 && Math.abs(dy) < 10) return; // not enough movement to tell yet
    intent = (dx > 0 && Math.abs(dx) > Math.abs(dy) * 1.15) ? 'back' : 'none';
    if(intent !== 'back'){ tracking = false; return; }
  }
  if(intent !== 'back') return;
  if(e.cancelable) e.preventDefault(); // confirmed horizontal drag -- stop the page from also panning/selecting
  setPull(Math.max(0, dx), false);
}, {passive: false});

function endDrag(e){
  if(!tracking || intent !== 'back'){ tracking = false; intent = null; return; }
  tracking = false;
  var t = (e.changedTouches && e.changedTouches[0]) || null;
  var dx = t ? t.clientX - startX : 0;
  intent = null;
  if(dx >= THRESHOLD){
    setPull(MAX_PULL, true);
    goBack();
  } else {
    resetPull();
  }
}
document.addEventListener('touchend', endDrag, {passive: true});
document.addEventListener('touchcancel', function(){ tracking = false; intent = null; resetPull(); }, {passive: true});
})();
