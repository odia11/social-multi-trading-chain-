/* Keep touch scrolling native; suppress only gestures escaping a scroll boundary. */
(function(){
'use strict';
if(window.__oaScrollGuardInstalled) return;
window.__oaScrollGuardInstalled=true;

// Apply on every route and viewport size, including landscape phones/tablets.
var style=document.createElement('style');
style.textContent='html,body{overscroll-behavior-y:none!important}';
document.head.appendChild(style);

var lastX=0,lastY=0,tracking=false;
function canScroll(target,dy){
  var root=document.scrollingElement||document.documentElement;
  for(var el=target;el&&el!==document;el=el.parentElement){
    if(el.nodeType!==1) continue;
    var isRoot=el===root;
    if(!isRoot&&!/^(auto|scroll|overlay)$/.test(getComputedStyle(el).overflowY)) continue;
    var max=el.scrollHeight-el.clientHeight;
    if(max>0&&((dy>0&&el.scrollTop>0.5)||(dy<0&&el.scrollTop<max-0.5))) return true;
    // A contained scroller does not pass its gesture to the page underneath.
    if(!isRoot&&/^(contain|none)$/.test(getComputedStyle(el).overscrollBehaviorY)) return false;
  }
  return false;
}
document.addEventListener('touchstart',function(e){
  tracking=e.touches.length===1;
  if(!tracking) return;
  lastX=e.touches[0].clientX;
  lastY=e.touches[0].clientY;
},{passive:true,capture:true});
document.addEventListener('touchmove',function(e){
  if(!tracking||e.touches.length!==1){tracking=false;return;}
  var x=e.touches[0].clientX,y=e.touches[0].clientY;
  var dx=x-lastX,dy=y-lastY;
  // Update each move so reversing direction immediately permits scrolling.
  lastX=x;lastY=y;
  if(!e.cancelable||!dy||Math.abs(dx)>Math.abs(dy)) return;
  if(!canScroll(e.target,dy)) e.preventDefault();
},{passive:false,capture:true});
function stop(){tracking=false;}
document.addEventListener('touchend',stop,{passive:true,capture:true});
document.addEventListener('touchcancel',stop,{passive:true,capture:true});
})();
