(function(){
  'use strict';
  var dialog, busy=false, lastFocus;
  function node(tag,text,cls){var n=document.createElement(tag);if(text)n.textContent=text;if(cls)n.className=cls;return n;}
  function show(data,personal){
    if(dialog)dialog.remove();
    lastFocus=document.activeElement;dialog=node('dialog',null,'oa-share-dialog');dialog.setAttribute('aria-labelledby','oa-share-title');
    var close=node('button','Close','oa-share-close');close.type='button';close.onclick=function(){dialog.close();};dialog.appendChild(close);
    var title=node('h2','Share this call');title.id='oa-share-title';dialog.appendChild(title);
    var image=node('img');image.src=data.card_url;image.alt='OrcAgent call card with the recorded entry and analysis';dialog.appendChild(image);
    var label=node('label','Call invitation link');var input=node('input');input.value=data.url;input.readOnly=true;label.appendChild(input);dialog.appendChild(label);
    var actions=node('div',null,'oa-share-actions'),status=node('p',personal?'This link credits new accounts to your invitation.':'Connect your wallet to track invitations from your own link.');status.setAttribute('role','status');
    var copy=node('button','Copy link');copy.type='button';copy.onclick=function(){
      (navigator.clipboard?navigator.clipboard.writeText(data.url):Promise.reject(new Error('Clipboard unavailable'))).then(function(){status.textContent='Link copied.';}).catch(function(){input.focus();input.select();status.textContent='Select and copy the link above.';});
    };actions.appendChild(copy);
    if(navigator.share){var native=node('button','Share…');native.type='button';native.onclick=function(){navigator.share({title:'OrcAgent token call',text:data.text,url:data.url}).catch(function(e){if(e.name!=='AbortError')status.textContent='Could not open sharing. Copy the link instead.';});};actions.appendChild(native);}
    var x=node('a','Share on X');x.href='https://twitter.com/intent/tweet?text='+encodeURIComponent(data.text)+'&url='+encodeURIComponent(data.url);x.target='_blank';x.rel='noopener noreferrer';actions.appendChild(x);
    var download=node('a','Save card');download.href=data.card_url;download.download='orcagent-call.png';actions.appendChild(download);
    dialog.appendChild(actions);dialog.appendChild(status);document.body.appendChild(dialog);dialog.addEventListener('close',function(){if(lastFocus&&lastFocus.isConnected)lastFocus.focus();});dialog.showModal();
  }
  async function share(id){
    if(busy||!/^\d+$/.test(String(id)))return;busy=true;
    try{
      var token=await fetch('/api/csrf-token',{credentials:'same-origin',cache:'no-store'}).then(function(r){return r.json();});
      var response=await fetch('/api/calls/'+id+'/share',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'X-CSRF-Token':token.token}});
      var data=await response.json();
      if(response.status===401){show({url:'https://orcagent.fun/call/'+id,card_url:'/api/call-card/'+id+'.png',text:'View this Solana token call on OrcAgent'},false);return;}
      if(!response.ok||!data.ok)throw new Error(data.msg||'Could not create a share link. Try again.');
      show(data,true);
    }catch(e){show({url:'https://orcagent.fun/call/'+id,card_url:'/api/call-card/'+id+'.png',text:'View this call on OrcAgent'},false);dialog.querySelector('[role="status"]').textContent=e.message;}
    finally{busy=false;}
  }
  document.addEventListener('click',function(e){var button=e.target.closest('.oa-share-call');if(!button)return;e.preventDefault();e.stopPropagation();share(button.dataset.callId);},true);
  // A server-signed session remembers the explicit Connect & return choice
  // across Phantom round trips; no browser storage or external redirect URL.
  if(location.pathname==='/'){
    var attempts=0;
    function returnToCall(){
      fetch('/api/invitations/return',{credentials:'same-origin',cache:'no-store'}).then(function(r){return r.ok?r.json():null;}).then(function(d){
        if(d&&/^\/call\/\d+$/.test(d.path||'')){location.replace(d.path);return;}
        if(d&&d.pending&&++attempts<90)setTimeout(returnToCall,2000);
      }).catch(function(){if(++attempts<90)setTimeout(returnToCall,2000);});
    }
    returnToCall();
  }
})();
