/* Suppress browser pull-to-refresh without intercepting native touch scrolling. */
(function(){
'use strict';
if(document.getElementById('oa-overscroll-style')) return;
var style=document.createElement('style');
style.id='oa-overscroll-style';
style.textContent='html,body{overscroll-behavior-y:none!important}';
document.head.appendChild(style);
// Do not cancel document touchmove. On Home, body expands with its contents
// while html owns scrolling; treating body as a bounded scroller blocks every
// vertical swipe. CSS overscroll control preserves scrolling and pinch zoom.
})();
