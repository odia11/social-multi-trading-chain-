(function(){
  'use strict';
  var csrf=document.querySelector('meta[name="csrf-token"]').content;
  var traders=document.getElementById('following-list'), calls=document.getElementById('following-calls');
  var status=document.getElementById('following-status'), more=document.getElementById('following-more');
  var cursor=null, globalOn=true, prefsBusy=false, callsBusy=false;
  function api(path,method,body){return fetch(path,{method:method||'GET',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body===undefined?undefined:JSON.stringify(body)}).then(function(r){return r.json().then(function(d){if(!r.ok||d.ok===false)throw new Error(d.msg||'Could not complete this request. Refresh and try again.');return d;});});}
  function empty(container,text){var p=document.createElement('p');p.className='muted';p.textContent=text;container.appendChild(p);}
  function profile(wallet){return '/profile/'+encodeURIComponent(wallet);}
  function loadTraders(append){
    if(prefsBusy)return Promise.resolve();prefsBusy=true;traders.setAttribute('aria-busy','true');more.disabled=true;
    return api('/api/following/preferences'+(append&&cursor?'?before='+cursor:'')).then(function(d){
      globalOn=d.notifications_enabled!==false;document.getElementById('following-global-off').hidden=globalOn;
      if(!append)traders.replaceChildren();
      if(!d.traders.length&&!append)empty(traders,'Follow a trader from their profile or Discover traders. Alerts stay off until you choose to enable them.');
      d.traders.forEach(function(t){
        var card=document.getElementById('following-trader-template').content.cloneNode(true);
        var name=card.querySelector('.following-name');name.textContent=t.username;name.href=profile(t.wallet);
        card.querySelector('.following-verified').hidden=!t.verified;
        card.querySelector('.following-wallet').textContent=t.wallet.slice(0,8)+'…'+t.wallet.slice(-5);
        var select=card.querySelector('.following-mode'), saved=t.mode;
        select.value=saved;select.setAttribute('aria-label','Alerts for '+t.username);
        select.addEventListener('change',function(){
          var selected=select.value;select.disabled=true;
          api('/api/following/preferences/'+t.user_id,'PUT',{mode:selected}).then(function(d){saved=d.mode;status.textContent='Preference saved for '+t.username+'.'+(globalOn?'':' Global notifications are off; enable them in Settings.');}).catch(function(e){select.value=saved;status.textContent=e.message;}).finally(function(){select.disabled=false;});
        });
        traders.appendChild(card);
      });
      cursor=d.next_cursor;more.hidden=!cursor;
    }).catch(function(e){status.textContent=e.message;}).finally(function(){prefsBusy=false;traders.setAttribute('aria-busy','false');more.disabled=false;});
  }
  function loadCalls(){
    if(callsBusy)return;callsBusy=true;calls.setAttribute('aria-busy','true');
    return api('/api/following/calls').then(function(d){
      calls.replaceChildren();if(!d.calls.length)empty(calls,'No Solana calls from the traders you follow yet. Their latest calls will appear here.');
      d.calls.forEach(function(c){
        var card=document.getElementById('following-call-template').content.cloneNode(true), author=card.querySelector('.following-author');
        author.textContent=c.username+(c.verified?' ✓':'');author.href=profile(c.wallet);
        card.querySelector('.following-symbol').textContent='$'+c.symbol;
        var time=card.querySelector('time'), date=new Date(String(c.created_at||'').replace(' ','T')+'Z');
        time.textContent=Number.isNaN(date.getTime())?'':date.toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
        if(!Number.isNaN(date.getTime()))time.dateTime=date.toISOString();
        var price=Number(c.price_at_call);card.querySelector('.following-entry').textContent=Number.isFinite(price)&&price>0?'Price at call: $'+price.toLocaleString('en-US',{maximumSignificantDigits:8})+' USD':'';
        card.querySelector('.oa-share-call').dataset.callId=c.id;
        card.querySelector('.following-note').textContent=c.note;card.querySelector('.following-trade').href='/live-market?mint='+encodeURIComponent(c.mint);
        var analysis=card.querySelector('.following-analysis');if(Number.isInteger(c.post_id)&&c.post_id>0){analysis.hidden=false;analysis.href='/#post-p'+c.post_id;}
        var watch=card.querySelector('.following-watch');watch.addEventListener('click',function(){
          watch.disabled=true;api('/api/watchlist/'+encodeURIComponent(c.mint),'POST',{symbol:c.symbol}).then(function(){watch.textContent='Saved to watchlist';status.textContent='Token saved. Set a price alert in Watchlist & alerts.';}).catch(function(e){status.textContent=e.message;watch.disabled=false;});
        });
        calls.appendChild(card);
      });
    }).catch(function(e){status.textContent=e.message;}).finally(function(){callsBusy=false;calls.setAttribute('aria-busy','false');});
  }
  more.addEventListener('click',function(){loadTraders(true);});
  loadTraders(false);loadCalls();setInterval(function(){if(!document.hidden)loadCalls();},60000);
})();
