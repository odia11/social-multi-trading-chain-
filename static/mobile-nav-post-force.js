/* Force the mobile center action to be Post even if Safari cached an older nav bundle. */
(function(){
'use strict';
if(!window.matchMedia('(max-width:767px)').matches)return;
function here(){return location.pathname.replace(/\/+$/,'')||'/'}
function focusComposer(attempt){
  attempt=attempt||0;
  var composer=document.getElementById('feed-composer');
  var input=document.getElementById('postText');
  if(!composer||!input){if(attempt<15)setTimeout(function(){focusComposer(attempt+1)},80);return;}
  composer.classList.add('expanded');
  try{composer.scrollIntoView({behavior:'smooth',block:'center'});}catch(e){composer.scrollIntoView();}
  setTimeout(function(){try{input.focus({preventScroll:true});}catch(e){input.focus();}},260);
}
function openComposer(){
  if(here()!=='/'){
    location.href='/?compose=1#feed-composer';
    return;
  }
  focusComposer(0);
}
function forceButton(){
  var btn=document.querySelector('.oa-bottom-nav .oa-trade-main, .oa-bottom-nav .oa-post-main');
  if(!btn)return false;
  btn.classList.add('oa-post-main');
  btn.setAttribute('aria-label','Create post');
  var label=btn.querySelector('span');if(label)label.textContent='Post';
  var svg=btn.querySelector('svg');if(svg)svg.innerHTML='<path d="M12 5v14"></path><path d="M5 12h14"></path>';
  return true;
}
document.addEventListener('click',function(e){
  var btn=e.target.closest&&e.target.closest('.oa-bottom-nav .oa-trade-main, .oa-bottom-nav .oa-post-main');
  if(!btn)return;
  e.preventDefault();e.stopPropagation();e.stopImmediatePropagation();
  openComposer();
},true);
function boot(){
  if(forceButton())return;
  var n=0,t=setInterval(function(){n++;if(forceButton()||n>30)clearInterval(t);},100);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
