/* Keep feed share dropdowns fully visible on mobile Safari/Phantom.
   iOS can treat position:fixed as local to a transformed/contained ancestor,
   so the menu is physically portaled to <body> while open. */
(function(){
'use strict';
if(!window.matchMedia('(max-width:767px)').matches)return;

var active=null;
var activeHome=null;
var activeNext=null;
var activeBtn=null;

function isOpen(dd){
  if(!dd)return false;
  if(dd.style.display==='none')return false;
  try{return getComputedStyle(dd).display!=='none'}catch(e){return true}
}

function restoreMenu(){
  if(!active)return;
  active.classList.remove('oa-share-floating');
  active.style.left='';
  active.style.top='';
  active.style.right='';
  active.style.bottom='';
  active.style.visibility='';
  active.style.width='';
  if(activeHome){
    try{
      if(activeNext && activeNext.parentNode===activeHome) activeHome.insertBefore(active,activeNext);
      else activeHome.appendChild(active);
    }catch(e){}
  }
  active=null;activeHome=null;activeNext=null;activeBtn=null;
}

function closeAndRestore(){
  if(active){active.style.display='none';}
  restoreMenu();
}

function placeActive(){
  if(!active||!activeBtn||!isOpen(active)){restoreMenu();return;}
  active.style.visibility='hidden';
  active.style.left='12px';
  active.style.top='12px';
  active.style.right='auto';
  active.style.bottom='auto';
  requestAnimationFrame(function(){
    if(!active||!activeBtn||!isOpen(active)){restoreMenu();return;}
    var br=activeBtn.getBoundingClientRect();
    var mr=active.getBoundingClientRect();
    var pad=12,gap=8,vw=document.documentElement.clientWidth||window.innerWidth;
    var vh=window.innerHeight||document.documentElement.clientHeight;
    var width=Math.min(Math.max(180,mr.width||180),vw-pad*2);
    active.style.width=Math.round(width)+'px';
    mr=active.getBoundingClientRect();
    var left=Math.min(Math.max(pad,br.right-mr.width),vw-mr.width-pad);
    var above=br.top-gap-mr.height;
    var below=br.bottom+gap;
    var top;
    if(above>=pad) top=above;
    else if(below+mr.height<=vh-pad) top=below;
    else top=Math.max(pad,Math.min(vh-mr.height-pad,br.top-(mr.height/2)));
    active.style.left=Math.round(left)+'px';
    active.style.top=Math.round(top)+'px';
    active.style.visibility='visible';
  });
}

function portalMenu(btn){
  var wrap=btn&&btn.closest('.fc-share-wrap');
  var dd=wrap&&wrap.querySelector('.fc-share-dd');
  if(!dd)return;

  /* The original inline handler has already toggled display by the time this
     runs (scheduled with setTimeout below). A second tap therefore closes. */
  if(!isOpen(dd)){
    if(active===dd)restoreMenu();
    return;
  }

  if(active&&active!==dd) closeAndRestore();
  if(active!==dd){
    active=dd;
    activeHome=dd.parentNode;
    activeNext=dd.nextSibling;
    activeBtn=btn;
    dd.classList.add('oa-share-floating');
    document.body.appendChild(dd);
  }else{
    activeBtn=btn;
  }
  placeActive();
}

document.addEventListener('click',function(e){
  var btn=e.target.closest&&e.target.closest('.fc-share-btn');
  if(btn){
    setTimeout(function(){portalMenu(btn)},0);
    return;
  }
  if(active){
    if(e.target.closest&&e.target.closest('.fc-share-dd')){
      /* Share action buttons close their own dropdown in the normal flow.
         Restore the node after that handler has run. */
      setTimeout(function(){if(active&&!isOpen(active))restoreMenu()},0);
      return;
    }
    closeAndRestore();
  }
},false);

window.addEventListener('scroll',function(){if(active)placeActive()},{passive:true});
window.addEventListener('resize',function(){if(active)placeActive()},{passive:true});
window.addEventListener('orientationchange',function(){setTimeout(function(){if(active)placeActive()},80)},{passive:true});
document.addEventListener('visibilitychange',function(){if(document.hidden)restoreMenu()},{passive:true});
})();
