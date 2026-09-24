/* Instagram-style pull-to-refresh, used on every page that calls
 *
 *   initPullToRefresh({onRefresh:function(){return promise}})
 *
 * Pull down while at the very top, release past the threshold, and a gold
 * spinner shows while onRefresh() refetches the page's data in place. A page
 * that passes no onRefresh (mostly server-rendered pages: profile,
 * leaderboard, traders, info...) gets a normal reload instead, the same
 * thing the browser's own pull-to-refresh would do. pull:false opts a page
 * out.
 *
 * All touch listeners are passive and nothing calls preventDefault, so
 * native scrolling, momentum and pinch zoom are untouched. A pull only
 * starts when the first movement is mostly downward and neither the page nor
 * any scrollable box under the finger is scrolled down. Touches that start
 * in a fixed/sticky layer (modals, sheets, menus, bottom nav, an open chat
 * thread) or on opts.ignoreTarget never start one. mobile-overscroll-guard.js
 * turns the browser's own pull-to-refresh off, so there's nothing native to
 * fight with.
 */
(function(){
'use strict';
var THRESHOLD=72, MAX_PULL=120, MIN_SPIN_MS=650, MAX_SPIN_MS=15000;

function scrollTop(){
  var se=document.scrollingElement||document.documentElement;
  return Math.max(window.pageYOffset||0,se?se.scrollTop:0,document.body?document.body.scrollTop:0);
}
// Touches that start inside a modal, sheet, menu or the bottom nav belong to
// that layer, not the page, so they never start a pull.
function inOverlay(node){
  for(var el=node;el&&el!==document.body&&el.nodeType===1;el=el.parentElement){
    var pos=getComputedStyle(el).position;
    if(pos==='fixed'||pos==='sticky')return true;
  }
  return false;
}
// On pages that scroll an inner box instead of the document, "at the top"
// has to mean that box too -- otherwise pulling down to scroll back up a
// feed would fire a refresh.
function innerScrolled(node){
  for(var el=node;el&&el!==document.body&&el!==document.documentElement&&el.nodeType===1;el=el.parentElement){
    if(el.scrollTop>0&&el.scrollHeight>el.clientHeight+1){
      var oy=getComputedStyle(el).overflowY;
      if(oy==='auto'||oy==='scroll'||oy==='overlay')return true;
    }
  }
  return false;
}

function injectStyle(){
  if(document.getElementById('oa-ptr-style'))return;
  var s=document.createElement('style');s.id='oa-ptr-style';
  s.textContent=
    '#oa-ptr{position:fixed;left:50%;top:0;z-index:210;width:40px;height:40px;margin-left:-20px;border-radius:50%;'+
    'background:#152025;border:1px solid #344148;box-shadow:0 6px 18px rgba(0,0,0,.35);display:flex;align-items:center;'+
    'justify-content:center;pointer-events:none;opacity:0;transform:translate3d(0,-60px,0);will-change:transform,opacity}'+
    '#oa-ptr svg{display:block;width:22px;height:22px}'+
    '#oa-ptr.oa-ptr-anim{transition:transform .28s cubic-bezier(.2,.8,.2,1),opacity .28s}'+
    '#oa-ptr.oa-ptr-armed{border-color:rgba(247,185,85,.6)}'+
    '#oa-ptr.oa-ptr-spin svg{animation:oa-ptr-rot .8s linear infinite}'+
    '@keyframes oa-ptr-rot{to{transform:rotate(360deg)}}'+
    '@media (prefers-reduced-motion:reduce){#oa-ptr.oa-ptr-spin svg{animation-duration:2s}}';
  document.head.appendChild(s);
}
function makeIndicator(){
  var d=document.createElement('div');d.id='oa-ptr';d.setAttribute('aria-hidden','true');
  // A gold arc that grows with the pull, then spins while refreshing.
  d.innerHTML='<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5" fill="none" stroke="#344148" stroke-width="2.4"/>'+
    '<circle class="oa-ptr-arc" cx="12" cy="12" r="8.5" fill="none" stroke="#f7b955" stroke-width="2.4" stroke-linecap="round" '+
    'stroke-dasharray="53.4" stroke-dashoffset="53.4" transform="rotate(-90 12 12)"/></svg>';
  document.body.appendChild(d);
  return d;
}
function headerBottom(){
  var h=document.querySelector('.pt-nb-topbar');
  var b=h?h.getBoundingClientRect().bottom:0;
  return Math.max(0,b||0);
}

window.initPullToRefresh=function(opts){
  opts=opts||{};
  if(opts.pull===false)return;
  if(window.__oaPtrInit)return;window.__oaPtrInit=true;
  var onRefresh=typeof opts.onRefresh==='function'?opts.onRefresh:function(){
    location.reload();
    return new Promise(function(){});   // keep spinning until the new page replaces this one
  };
  // A page whose content lives in its own inner scroller while some mode is
  // active (an open chat thread) passes scrollEl; while it returns an
  // element, pulling is off -- dragging down there means "scroll up".
  function customScrollerActive(){try{return !!(typeof opts.scrollEl==='function'&&opts.scrollEl())}catch(_){return false}}

  var ind=null,arc=null,startX=0,startY=0,tracking=false,pulling=false,dist=0,refreshing=false,armedOnce=false;

  function ensure(){if(!ind){injectStyle();ind=makeIndicator();arc=ind.querySelector('.oa-ptr-arc');}}
  function place(y,opacity,progress,anim){
    ensure();
    ind.classList.toggle('oa-ptr-anim',!!anim);
    ind.style.top=headerBottom()+'px';
    ind.style.transform='translate3d(0,'+(y-50)+'px,0) rotate('+(progress*270)+'deg)';
    ind.style.opacity=String(opacity);
    if(arc)arc.setAttribute('stroke-dashoffset',String(53.4*(1-Math.min(1,progress)*.85)));
  }
  function hide(){
    if(!ind)return;
    ind.classList.remove('oa-ptr-spin','oa-ptr-armed');
    place(0,0,0,true);
  }
  function run(){
    refreshing=true;ensure();
    ind.classList.add('oa-ptr-spin');
    place(THRESHOLD*.8,1,.9,true);
    var started=Date.now(),p;
    try{p=Promise.resolve(onRefresh());}catch(e){p=Promise.resolve();}
    var cap=new Promise(function(res){setTimeout(res,MAX_SPIN_MS)});
    Promise.race([p.catch(function(){}),cap]).then(function(){
      var wait=Math.max(0,MIN_SPIN_MS-(Date.now()-started));
      setTimeout(function(){refreshing=false;hide();},wait);
    });
  }

  document.addEventListener('touchstart',function(e){
    tracking=pulling=false;dist=0;armedOnce=false;
    if(refreshing||e.touches.length!==1)return;
    if(scrollTop()>0||customScrollerActive()||inOverlay(e.target)||innerScrolled(e.target))return;
    if(opts.ignoreTarget&&e.target&&e.target.closest&&e.target.closest(opts.ignoreTarget))return;
    tracking=true;startX=e.touches[0].clientX;startY=e.touches[0].clientY;
  },{passive:true});

  document.addEventListener('touchmove',function(e){
    if(!tracking||e.touches.length!==1)return;
    var dx=e.touches[0].clientX-startX,dy=e.touches[0].clientY-startY;
    if(!pulling){
      if(Math.abs(dx)<6&&Math.abs(dy)<6)return;
      // Upward or sideways first movement: this is a scroll/swipe, not a pull.
      if(dy<=0||Math.abs(dx)>Math.abs(dy)||scrollTop()>0){tracking=false;return;}
      pulling=true;
    }
    if(scrollTop()>0){tracking=pulling=false;hide();return;}
    // Rubber-band resistance, like native iOS/Instagram.
    dist=Math.min(MAX_PULL,Math.max(0,dy)*.5);
    var progress=dist/THRESHOLD;
    place(dist,Math.min(1,progress*1.2),progress,false);
    var armed=dist>=THRESHOLD;
    ind.classList.toggle('oa-ptr-armed',armed);
    if(armed&&!armedOnce){armedOnce=true;try{navigator.vibrate&&navigator.vibrate(8)}catch(_){}}
    if(!armed)armedOnce=false;
  },{passive:true});

  function end(){
    if(!tracking)return;
    tracking=false;
    if(pulling&&dist>=THRESHOLD&&!refreshing)run();
    else if(pulling)hide();
    pulling=false;dist=0;
  }
  document.addEventListener('touchend',end,{passive:true});
  document.addEventListener('touchcancel',function(){tracking=pulling=false;dist=0;if(!refreshing)hide();},{passive:true});
};
})();
