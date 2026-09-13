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
  var main=document.querySelector('.msgs-main');
  var open=!!(main&&main.classList.contains('thread-open'));
  document.body.classList.toggle('oa-thread-open',open);
  if(open)decorateIncoming();
}

function run(){markThreadState();if(document.body.classList.contains('oa-thread-open'))decorateIncoming();}
var pending=false;
var mo=new MutationObserver(function(){
  if(pending)return;
  pending=true;
  requestAnimationFrame(function(){pending=false;run();});
});
function start(){
  run();
  var main=document.querySelector('.msgs-main');
  if(main)mo.observe(main,{childList:true,subtree:true,attributes:true,attributeFilter:['class','style']});
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
