(function(){
  'use strict';
  var status=document.getElementById('invitations-status'),list=document.getElementById('invitation-shares'),refresh=document.getElementById('invitations-refresh'),busy=false;
  async function load(){
    if(busy)return;busy=true;refresh.disabled=true;list.setAttribute('aria-busy','true');
    try{
      var r=await fetch('/api/invitations',{credentials:'same-origin',cache:'no-store'}),d=await r.json();
      if(!r.ok||!d.ok)throw new Error(d.msg||'Could not load invitation totals.');
      ['links','signups','traders','trades'].forEach(function(k){document.getElementById('invite-'+k).textContent=Number(d[k==='links'?'share_links':k]).toLocaleString();});
      document.getElementById('invite-volume').textContent=Number(d.volume_usdc).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})+' USDC';
      list.replaceChildren();status.textContent='';
      if(!d.shares.length){var p=document.createElement('p');p.className='muted';p.textContent='Share a call from Home, Calls or Following. Your personal links will appear here.';list.appendChild(p);}
      d.shares.forEach(function(s){
        var card=document.getElementById('invitation-share-template').content.cloneNode(true);
        card.querySelector('.invite-symbol').textContent='$'+s.symbol;
        card.querySelector('.invite-date').textContent=new Date(s.created_at*1000).toLocaleString();
        card.querySelector('.invite-conversions').textContent=s.signups+' new account'+(s.signups===1?'':'s');
        card.querySelector('.invite-open').href=s.url;
        card.querySelector('.invite-copy').onclick=function(){(navigator.clipboard?navigator.clipboard.writeText(s.url):Promise.reject(new Error('Clipboard unavailable'))).then(function(){status.textContent='Invitation link copied.';}).catch(function(){status.textContent='Copy the link from the shared call page.';});};list.appendChild(card);
      });
    }catch(e){status.textContent=e.message;}finally{busy=false;refresh.disabled=false;list.setAttribute('aria-busy','false');}
  }
  refresh.addEventListener('click',load);load();
})();
