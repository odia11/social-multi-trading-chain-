/* OrcAgent Messages Thread v6 runtime enforcement */
(function(){
'use strict';
if(!window.matchMedia('(max-width:767px)').matches)return;
var navDisplay='';
function isOpen(){
  var main=document.querySelector('.msgs-main');
  var thread=document.getElementById('msgs-thread');
  return !!((main&&main.classList.contains('thread-open'))||(thread&&getComputedStyle(thread).display!=='none'));
}
function setImportant(el,prop,val){if(el)el.style.setProperty(prop,val,'important')}
function clear(el,props){if(!el)return;props.forEach(function(p){el.style.removeProperty(p)})}
function sync(){
  var open=isOpen();
  document.body.classList.toggle('oa-thread-open',open);
  document.documentElement.classList.toggle('oa-thread-open',open);

  var nav=document.getElementById('oa-bottom-nav')||document.querySelector('.oa-bottom-nav');
  if(nav){
    if(open){
      if(navDisplay==='')navDisplay=nav.style.display||'';
      nav.style.setProperty('display','none','important');
      nav.setAttribute('aria-hidden','true');
    }else{
      nav.style.removeProperty('display');
      if(navDisplay)nav.style.display=navDisplay;
      nav.removeAttribute('aria-hidden');
    }
  }
  var top=document.querySelector('.pt-nb-topbar');
  if(top){if(open)top.style.setProperty('display','none','important');else top.style.removeProperty('display');}

  var app=document.getElementById('app');
  var main=document.querySelector('.msgs-main');
  var right=document.getElementById('msgs-right');
  var thread=document.getElementById('msgs-thread');
  if(open){
    setImportant(document.body,'padding-bottom','0px');
    [app,main,right].forEach(function(el){
      if(!el)return;
      setImportant(el,'position','fixed');
      setImportant(el,'top','0px');setImportant(el,'right','0px');setImportant(el,'bottom','0px');setImportant(el,'left','0px');
      setImportant(el,'width','100vw');setImportant(el,'height','100dvh');setImportant(el,'max-height','100dvh');
      setImportant(el,'margin','0px');setImportant(el,'padding','0px');setImportant(el,'overflow','hidden');
    });
    if(thread){
      setImportant(thread,'position','absolute');
      setImportant(thread,'top','0px');setImportant(thread,'right','0px');setImportant(thread,'bottom','0px');setImportant(thread,'left','0px');
      setImportant(thread,'display','flex');setImportant(thread,'flex-direction','column');setImportant(thread,'height','100%');setImportant(thread,'overflow','hidden');
    }
  }else{
    document.body.style.removeProperty('padding-bottom');
    [app,main,right,thread].forEach(function(el){clear(el,['position','top','right','bottom','left','width','height','max-height','margin','padding','overflow','display','flex-direction'])});
  }
}
var pending=false;
var mo=new MutationObserver(function(){if(pending)return;pending=true;requestAnimationFrame(function(){pending=false;sync();});});
function start(){
  sync();
  mo.observe(document.documentElement,{childList:true,subtree:true,attributes:true,attributeFilter:['class','style']});
  window.addEventListener('pageshow',sync);
  window.addEventListener('resize',sync);
  if(window.visualViewport){window.visualViewport.addEventListener('resize',sync);}
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
