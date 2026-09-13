/* OrcAgent Messages Thread v5 runtime — completes approved fullscreen chat layout. */
(function(){
'use strict';
if(!window.matchMedia('(max-width:767px)').matches)return;

function peerAvatarTemplate(){
  var hdr=document.getElementById('msgs-thread-hdr');
  if(!hdr)return null;
  var src=hdr.querySelector('.msgs-thread-avatar');
  if(!src)return null;
  var el=document.createElement('div');
  el.className='oa-peer-mini-avatar';
  var img=src.querySelector('img');
  if(img&&img.src){
    var copy=document.createElement('img');copy.src=img.src;copy.alt='';el.appendChild(copy);
  }else{
    el.style.background=src.style.background||'#111720';
    el.textContent=(src.textContent||'?').trim().slice(0,2);
  }
  return el;
}

function decorateIncoming(){
  var template=peerAvatarTemplate();
  if(!template)return;
  document.querySelectorAll('#msgs-area .msg-wrap.theirs').forEach(function(row){
    if(row.querySelector(':scope > .oa-peer-mini-avatar'))return;
    row.insertBefore(template.cloneNode(true),row.firstChild);
  });
}

function markThreadState(){
  var thread=document.getElementById('msgs-thread');
  var open=!!(thread&&getComputedStyle(thread).display!=='none');
  document.body.classList.toggle('oa-thread-open',open);
  if(open)decorateIncoming();
}

function run(){markThreadState();decorateIncoming();}
var mo=new MutationObserver(function(){requestAnimationFrame(run)});
function start(){run();mo.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['style','class']});}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
