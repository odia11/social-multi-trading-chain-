/* OrcAgent mobile feed share dropdown — direct portal implementation. */
(function(){
'use strict';
if(!window.matchMedia('(max-width:767px)').matches)return;

var active=null;
var activePostId='';
var placeholder=null;
var originalParent=null;
var originalNext=null;

function menuId(postId){ return 'fc-share-dd-'+String(postId||''); }
function cardId(postId){ return 'fc-card-'+String(postId||''); }

function restoreActive(){
  if(!active)return;
  active.style.display='none';
  active.classList.remove('oa-share-floating');
  active.style.left='';
  active.style.top='';
  active.style.visibility='';
  active.style.width='';
  active.style.maxWidth='';
  if(originalParent){
    if(placeholder && placeholder.parentNode===originalParent){
      originalParent.insertBefore(active,placeholder);
      placeholder.remove();
    }else if(originalNext && originalNext.parentNode===originalParent){
      originalParent.insertBefore(active,originalNext);
    }else{
      originalParent.appendChild(active);
    }
  }
  active=null;
  activePostId='';
  placeholder=null;
  originalParent=null;
  originalNext=null;
}

function getShareButton(postId){
  var card=document.getElementById(cardId(postId));
  if(card){
    var b=card.querySelector('.fc-share-btn');
    if(b)return b;
  }
  var buttons=document.querySelectorAll('.fc-share-btn');
  for(var i=0;i<buttons.length;i++){
    var oc=buttons[i].getAttribute('onclick')||'';
    if(oc.indexOf(String(postId))!==-1)return buttons[i];
  }
  return null;
}

function place(dd,btn){
  dd.style.visibility='hidden';
  dd.style.display='block';
  dd.style.left='12px';
  dd.style.top='12px';
  dd.style.width='auto';
  dd.style.maxWidth='calc(100vw - 24px)';

  requestAnimationFrame(function(){
    if(active!==dd)return;
    var br=btn?btn.getBoundingClientRect():{left:window.innerWidth-56,right:window.innerWidth-20,top:window.innerHeight/2,bottom:window.innerHeight/2};
    var mr=dd.getBoundingClientRect();
    var pad=12,gap=10,vw=document.documentElement.clientWidth||window.innerWidth,vh=window.innerHeight;
    var safeBottom=112; /* fixed OrcAgent bottom nav */
    var usableBottom=Math.max(pad,vh-safeBottom);
    var left=Math.min(Math.max(pad,br.right-mr.width),Math.max(pad,vw-mr.width-pad));
    var above=br.top-gap-mr.height;
    var below=br.bottom+gap;
    var top;
    if(above>=pad){
      top=above;
    }else if(below+mr.height<=usableBottom){
      top=below;
    }else{
      top=Math.max(pad,Math.min(usableBottom-mr.height,br.top-mr.height/2));
    }
    dd.style.left=Math.round(left)+'px';
    dd.style.top=Math.round(top)+'px';
    dd.style.visibility='visible';
  });
}

function openPortal(postId){
  postId=String(postId||'');
  var dd=document.getElementById(menuId(postId));
  var btn=getShareButton(postId);
  if(!dd)return false;

  if(active===dd){ restoreActive(); return true; }
  restoreActive();

  originalParent=dd.parentNode;
  originalNext=dd.nextSibling;
  placeholder=document.createComment('orca-share-menu-placeholder');
  if(originalParent)originalParent.insertBefore(placeholder,dd);

  document.body.appendChild(dd);
  active=dd;
  activePostId=postId;
  dd.classList.add('oa-share-floating');
  place(dd,btn);
  return true;
}

/* Override the feed's own inline onclick target. Inline handlers resolve the
   global at click time, so this prevents the old absolute dropdown from ever
   becoming visible on mobile. Wait until all dashboard scripts have executed. */
function installOverride(){
  window._fcShareToggle=function(postId){
    openPortal(postId);
  };
}
if(document.readyState==='loading'){
  window.addEventListener('load',installOverride,{once:true});
}else{
  setTimeout(installOverride,0);
}

/* Close only after the menu item's own inline handler has had a chance to run. */
document.addEventListener('click',function(e){
  if(!active)return;
  if(e.target.closest && e.target.closest('.fc-share-dd')){
    if(e.target.closest('.fc-share-item'))setTimeout(restoreActive,0);
    return;
  }
  if(e.target.closest && e.target.closest('.fc-share-btn'))return;
  restoreActive();
},false);

document.addEventListener('keydown',function(e){if(e.key==='Escape')restoreActive();});
window.addEventListener('scroll',restoreActive,{passive:true});
window.addEventListener('resize',restoreActive,{passive:true});
window.addEventListener('pagehide',restoreActive,{passive:true});
})();
