/* OrcAgent Messages Thread v6 runtime enforcement */
(function(){
'use strict';
if(!window.matchMedia('(max-width:767px)').matches)return;
var navDisplay='';
function isOpen(){var main=document.querySelector('.msgs-main');var thread=document.getElementById('msgs-thread');return !!((main&&main.classList.contains('thread-open'))||(thread&&getComputedStyle(thread).display!=='none'));}
function sync(){var open=isOpen();document.body.classList.toggle('oa-thread-open',open);var nav=document.getElementById('oa-bottom-nav')||document.querySelector('.oa-bottom-nav');if(nav){if(open){if(navDisplay==='')navDisplay=nav.style.display||'';nav.style.setProperty('display','none','important');nav.setAttribute('aria-hidden','true');}else{nav.style.removeProperty('display');if(navDisplay)nav.style.display=navDisplay;nav.removeAttribute('aria-hidden');}}
var top=document.querySelector('.pt-nb-topbar');if(top){if(open)top.style.setProperty('display','none','important');else top.style.removeProperty('display');}}
var mo=new MutationObserver(function(){requestAnimationFrame(sync)});
function start(){sync();mo.observe(document.documentElement,{childList:true,subtree:true,attributes:true,attributeFilter:['class','style']});window.addEventListener('pageshow',sync);window.addEventListener('resize',sync);}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
