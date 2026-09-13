/* OrcAgent Messages Composer v4 — compact wide textarea without replacing message logic. */
(function(){
'use strict';
if(!window.matchMedia('(max-width:767px)').matches)return;

function install(){
  var bar=document.querySelector('.msgs-input-bar');
  var old=document.getElementById('msgs-input');
  if(!bar||!old||bar.classList.contains('oa-composer-v4'))return;

  var ta=document.createElement('textarea');
  ta.id='msgs-input';
  ta.className=(old.className||'msgs-input')+' oa-msgs-textarea';
  ta.placeholder='Message…';
  ta.maxLength=2000;
  ta.rows=1;
  ta.setAttribute('aria-label','Message');
  ta.value=old.value||'';
  ta.addEventListener('keydown',function(e){
    if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();if(typeof window._sendMessage==='function')window._sendMessage();}
  });

  var wrap=document.createElement('div');
  wrap.className='oa-compose-text-wrap';
  var counter=document.createElement('span');
  counter.className='oa-msg-counter';
  counter.textContent='0/2000';
  wrap.appendChild(ta);wrap.appendChild(counter);
  old.replaceWith(wrap);
  bar.classList.add('oa-composer-v4');

  function resize(){
    ta.style.height='58px';
    var h=Math.max(58,Math.min(108,ta.scrollHeight));
    ta.style.height=h+'px';
    counter.textContent=(ta.value||'').length+'/2000';
  }
  ta.addEventListener('input',resize);
  resize();

  function setTyping(on){
    document.body.classList.toggle('oa-msgs-typing',on);
    if(!on)document.documentElement.style.removeProperty('--oa-kb-offset');
    updateViewport();
  }
  function updateViewport(){
    if(!document.body.classList.contains('oa-msgs-typing'))return;
    var vv=window.visualViewport;
    if(!vv){document.documentElement.style.setProperty('--oa-kb-offset','0px');return;}
    var offset=Math.max(0,window.innerHeight-vv.height-vv.offsetTop);
    document.documentElement.style.setProperty('--oa-kb-offset',offset+'px');
    var area=document.getElementById('msgs-area');
    if(area){requestAnimationFrame(function(){area.scrollTop=area.scrollHeight;});}
  }
  ta.addEventListener('focus',function(){setTyping(true);});
  ta.addEventListener('blur',function(){setTimeout(function(){if(document.activeElement!==ta)setTyping(false);},120);});
  if(window.visualViewport){
    window.visualViewport.addEventListener('resize',updateViewport);
    window.visualViewport.addEventListener('scroll',updateViewport);
  }

  /* Keep textarea height synced after sends and DOM refreshes. */
  var obs=new MutationObserver(function(){resize();});
  obs.observe(bar,{childList:true,subtree:true});
  document.addEventListener('click',function(e){
    if(e.target.closest('#msgs-send,.msgs-send,.msgs-send-btn'))setTimeout(resize,60);
  });
}

if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});else install();
var tries=0,t=setInterval(function(){tries++;install();if(document.querySelector('.msgs-input-bar.oa-composer-v4')||tries>20)clearInterval(t);},100);
})();
