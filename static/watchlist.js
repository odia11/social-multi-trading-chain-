(function(){
  'use strict';
  var csrf=document.querySelector('meta[name="csrf-token"]').content;
  var list=document.getElementById('watch-tokens'), status=document.getElementById('watch-status');
  var dialog=document.getElementById('watch-alert-dialog'), current=null, loading=false;
  var mintPattern=/^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
  function api(path,method,body){
    return fetch(path,{method:method||'GET',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body===undefined?undefined:JSON.stringify(body)}).then(function(r){
      return r.json().then(function(d){if(!r.ok||d.ok===false)throw new Error(d.msg||'Could not complete this request. Refresh and try again.');return d;});
    });
  }
  function price(v){var n=Number(v);return Number.isFinite(n)&&n>0?'$'+n.toLocaleString('en-US',{maximumSignificantDigits:8}):'Price unavailable';}
  function pairs(mints){
    var batches=[];for(var i=0;i<mints.length;i+=30)batches.push(mints.slice(i,i+30));
    return Promise.all(batches.map(function(batch){return api('/api/dexscreener/tokens/'+batch.join(',')).catch(function(){return {pairs:[]};});})).then(function(results){
      var best={};results.forEach(function(d){(d.pairs||[]).forEach(function(p){var m=(p.baseToken||{}).address;if(p.chainId!=='solana'||mints.indexOf(m)<0)return;if(!best[m]||Number((p.liquidity||{}).usd||0)>Number((best[m].liquidity||{}).usd||0))best[m]=p;});});return best;
    });
  }
  function load(){
    if(loading)return;loading=true;list.setAttribute('aria-busy','true');
    return Promise.all([api('/api/watchlist'),api('/api/price-alerts')]).then(function(data){
      var tokens=data[0].tokens||[], alerts=data[1].alerts||[];
      return pairs(tokens.map(function(t){return t.token_address;})).then(function(prices){
        list.replaceChildren();document.getElementById('watch-count').textContent='('+tokens.length+'/100)';
        if(!tokens.length){var empty=document.createElement('p');empty.className='muted';empty.textContent='Your watchlist is empty. Add a token address above or tap the star beside a token in Live Market.';list.appendChild(empty);}
        tokens.forEach(function(t){
          var p=prices[t.token_address]||{}, base=p.baseToken||{};
          var card=document.getElementById('watch-token-template').content.cloneNode(true);
          var symbol=base.symbol||t.symbol||t.token_address.slice(0,8);
          card.querySelector('.token-symbol').textContent=symbol;
          card.querySelector('.token-name').textContent=base.name||'Solana';
          card.querySelector('.token-price').textContent=price(p.priceUsd);
          card.querySelector('.token-address').textContent=t.token_address;
          card.querySelector('.trade-token').href='/live-market?mint='+encodeURIComponent(t.token_address);
          card.querySelector('.remove-token').addEventListener('click',function(e){
            e.currentTarget.disabled=true;api('/api/watchlist/'+encodeURIComponent(t.token_address),'DELETE').then(function(){status.textContent='Token removed; its alerts were cancelled.';return load();}).catch(function(err){status.textContent=err.message;e.target.disabled=false;});
          });
          card.querySelector('.alert-token').addEventListener('click',function(){
            current=t.token_address;document.getElementById('watch-alert-title').textContent='Alert for '+symbol;
            document.getElementById('watch-target').value=p.priceUsd||'';
            document.getElementById('watch-alert-error').textContent='';dialog.showModal();
          });
          var ul=card.querySelector('.token-alerts');
          alerts.filter(function(a){return a.mint===t.token_address;}).slice(0,20).forEach(function(a){
            var li=document.createElement('li'), label=document.createElement('span'), cancel=document.createElement('button');
            label.textContent=(a.active?'Waiting: ':'Reached: ')+a.direction+' '+price(a.target)+' USD';
            cancel.type='button';cancel.textContent=a.active?'Cancel':'Dismiss';
            cancel.addEventListener('click',function(){cancel.disabled=true;api('/api/price-alerts/'+a.id,'DELETE').then(load).catch(function(err){status.textContent=err.message;cancel.disabled=false;});});
            li.append(label,cancel);ul.appendChild(li);
          });
          list.appendChild(card);
        });
      });
    }).catch(function(err){status.textContent=err.message;}).finally(function(){loading=false;list.setAttribute('aria-busy','false');});
  }
  document.getElementById('watch-add').addEventListener('submit',function(e){
    e.preventDefault();var mint=document.getElementById('watch-mint').value.trim(), button=this.querySelector('button');
    if(!mintPattern.test(mint)){status.textContent='Enter a valid Solana token address.';return;}
    button.disabled=true;api('/api/watchlist/'+encodeURIComponent(mint),'POST',{symbol:''}).then(function(){document.getElementById('watch-mint').value='';status.textContent='Token added to your private watchlist.';return load();}).catch(function(err){status.textContent=err.message;}).finally(function(){button.disabled=false;});
  });
  document.getElementById('watch-alert-close').addEventListener('click',function(){dialog.close();});
  document.getElementById('watch-alert-form').addEventListener('submit',function(e){
    e.preventDefault();var button=this.querySelector('button[type="submit"]');button.disabled=true;
    api('/api/price-alerts','POST',{mint:current,direction:document.getElementById('watch-direction').value,target:document.getElementById('watch-target').value}).then(function(){dialog.close();status.textContent='Alert saved. We will notify you once when the target is reached.';return load();}).catch(function(err){document.getElementById('watch-alert-error').textContent=err.message;}).finally(function(){button.disabled=false;});
  });
  load();OrcPageLifecycle.setInterval(function(){if(!document.hidden&&!dialog.open)load();},60000);
})();
