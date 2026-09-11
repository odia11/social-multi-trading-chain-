/* OrcAgent mobile Home boundary guard.
   Prevents the host iOS/Phantom webview from turning fast feed scrolling into
   native pull-to-refresh / rubber-band overscroll. Normal document scrolling
   remains fully native between the top and bottom boundaries. */
(function(){
'use strict';
var path=location.pathname.replace(/\/+$/,'')||'/';
if(path!=='/' || !window.matchMedia('(max-width:767px)').matches) return;

document.documentElement.classList.add('oa-home-mobile-root');
if(document.body) document.body.classList.add('oa-home-mobile-boundary-guard');
else document.addEventListener('DOMContentLoaded',function(){document.body.classList.add('oa-home-mobile-boundary-guard')},{once:true});

var startY=0;
var tracking=false;

function scrollY(){
  return window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;
}
function maxScroll(){
  var d=document.documentElement,b=document.body;
  var h=Math.max(d.scrollHeight,d.offsetHeight,d.clientHeight,b?b.scrollHeight:0,b?b.offsetHeight:0);
  return Math.max(0,h-window.innerHeight);
}
function interactive(target){
  return !!(target&&target.closest&&target.closest('input,textarea,select,[contenteditable="true"],.feed-emoji-panel'));
}

document.addEventListener('touchstart',function(e){
  if(e.touches.length!==1){tracking=false;return;}
  startY=e.touches[0].clientY;
  tracking=true;
},{passive:true,capture:true});

document.addEventListener('touchmove',function(e){
  if(!tracking||e.touches.length!==1||!e.cancelable) return;
  if(interactive(e.target)) return;
  var y=e.touches[0].clientY;
  var dy=y-startY;
  var top=scrollY();
  var max=maxScroll();
  // Downward drag while already at the very top => Phantom/iOS refresh gesture.
  // Upward drag while already at the bottom => rubber-band bounce. Block only
  // those boundary drags; regular vertical scrolling is untouched.
  if((top<=0.5&&dy>0)||(top>=max-0.5&&dy<0)) e.preventDefault();
},{passive:false,capture:true});

function stop(){tracking=false;startY=0;}
document.addEventListener('touchend',stop,{passive:true,capture:true});
document.addEventListener('touchcancel',stop,{passive:true,capture:true});
})();
