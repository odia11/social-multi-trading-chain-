/* Keep feed share dropdowns fully visible on mobile Safari/Phantom. */
(function(){
'use strict';
if(!window.matchMedia('(max-width:767px)').matches)return;
var active=null;
function clearMenu(){
  if(!active)return;
  active.classList.remove('oa-share-floating');
  active.style.left='';active.style.top='';active.style.visibility='';
  active=null;
}
function placeMenu(btn){
  var wrap=btn&&btn.closest('.fc-share-wrap');
  var dd=wrap&&wrap.querySelector('.fc-share-dd');
  if(!dd||dd.style.display==='none')return;
  clearMenu();active=dd;
  dd.classList.add('oa-share-floating');
  dd.style.visibility='hidden';
  dd.style.left='12px';dd.style.top='12px';
  requestAnimationFrame(function(){
    if(!active||dd.style.display==='none'){clearMenu();return;}
    var br=btn.getBoundingClientRect(), mr=dd.getBoundingClientRect();
    var pad=12,gap=8,vw=window.innerWidth,vh=window.innerHeight;
    var left=Math.min(Math.max(pad,br.right-mr.width),vw-mr.width-pad);
    var above=br.top-gap-mr.height;
    var below=br.bottom+gap;
    var top=above>=pad?above:Math.min(below,vh-mr.height-pad);
    top=Math.max(pad,top);
    dd.style.left=Math.round(left)+'px';
    dd.style.top=Math.round(top)+'px';
    dd.style.visibility='visible';
  });
}
document.addEventListener('click',function(e){
  var btn=e.target.closest&&e.target.closest('.fc-share-btn');
  if(btn){setTimeout(function(){placeMenu(btn)},0);return;}
  if(active&&!e.target.closest('.fc-share-dd'))clearMenu();
},true);
window.addEventListener('scroll',clearMenu,{passive:true});
window.addEventListener('resize',clearMenu,{passive:true});
})();
