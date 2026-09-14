(function(){
'use strict';
var generated=null,bypass=false;
var AAD='orcagent-wallet-onboarding-v1';
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]);});}
function bytesToB64(bytes){var s='';for(var i=0;i<bytes.length;i++)s+=String.fromCharCode(bytes[i]);return btoa(s);}
function b64ToBytes(s){var raw=atob(s||'');var out=new Uint8Array(raw.length);for(var i=0;i<raw.length;i++)out[i]=raw.charCodeAt(i);return out;}
async function makeTransport(){if(!window.crypto||!crypto.subtle||!crypto.getRandomValues)throw new Error('Secure browser crypto is not available');var raw=crypto.getRandomValues(new Uint8Array(32));return{raw:raw,b64:bytesToB64(raw)};}
async function openSealed(d,raw){if(!d||!d.sealed||!d.nonce||d.alg!=='A256GCM')return d;var key=await crypto.subtle.importKey('raw',raw,{name:'AES-GCM'},false,['decrypt']);var pt=await crypto.subtle.decrypt({name:'AES-GCM',iv:b64ToBytes(d.nonce),additionalData:new TextEncoder().encode(AAD),tagLength:128},key,b64ToBytes(d.sealed));return JSON.parse(new TextDecoder().decode(pt));}
async function csrf(){
  if(window._csrfToken)return window._csrfToken;
  if(window._csrf)return window._csrf;
  try{var r=await fetch('/api/csrf',{credentials:'include',cache:'no-store'});var d=await r.json();return d.csrf_token||d.csrf||'';}catch(_){return '';}
}
async function post(url,body){var t=await csrf();var r=await fetch(url,{method:'POST',credentials:'include',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':t},body:JSON.stringify(body||{})});var d={};try{d=await r.json();}catch(_){}if(!r.ok||!d.ok)throw new Error(d.error||'Request failed');return d;}
function connectControl(){return document.getElementById('oa-guest-connect-btn')||document.querySelector('.pt-nb-profile-link[data-oa-auth="guest"]')||document.querySelector('#guest-banner .gb-link,.gb-link');}
function modal(){
  var m=document.getElementById('oa-wallet-onboarding');
  if(m)return m;
  m=document.createElement('div');m.id='oa-wallet-onboarding';m.className='oa-ob-backdrop';m.innerHTML='\
  <div class="oa-ob-card" role="dialog" aria-modal="true" aria-label="Wallet setup">\
    <button class="oa-ob-close" aria-label="Close">×</button>\
    <div class="oa-ob-brand">ORCAGENT</div><h2>Set up your wallet</h2><p class="oa-ob-sub">Create a new OrcAgent wallet or use one you already own.</p>\
    <div class="oa-ob-actions">\
      <button class="oa-ob-primary" data-action="create"><strong>Create New Wallet</strong><span>Generate a new self-custodial wallet and private keys.</span></button>\
      <button class="oa-ob-secondary" data-action="import"><strong>Import Existing Wallet</strong><span>Import with your Solana private key.</span></button>\
      <button class="oa-ob-secondary" data-action="phantom"><strong>Connect Phantom</strong><span>Use the wallet already in your Phantom app.</span></button>\
    </div><div class="oa-ob-stage" hidden></div>\
  </div>';
  document.body.appendChild(m);
  m.querySelector('.oa-ob-close').onclick=close;
  m.addEventListener('click',function(e){
    if(e.target===m)close();
    var b=e.target.closest('[data-action]');if(!b)return;
    var a=b.dataset.action;
    if(a==='create')showCreate();
    if(a==='import')showImport();
    if(a==='phantom'){
      close();bypass=true;
      var x=connectControl();
      if(x){try{x.click();}catch(_){}}
      else if(typeof window.connectWalletOnboard==='function'){try{window.connectWalletOnboard('phantom');}catch(_){}}
      else if(typeof window.connectWallet==='function'){try{window.connectWallet();}catch(_){}}
      setTimeout(function(){bypass=false},80);
    }
  });
  return m;
}
function open(){var m=modal();m.style.display='flex';var st=m.querySelector('.oa-ob-stage');st.hidden=true;m.querySelector('.oa-ob-actions').hidden=false;}
function close(){var m=document.getElementById('oa-wallet-onboarding');if(m)m.style.display='none';wipe();}
function wipe(){if(generated){generated.solana_private_key='';generated.evm_private_key='';generated=null;}document.querySelectorAll('.oa-ob-secret').forEach(function(x){x.value='';});}
function stage(html){var m=modal();m.querySelector('.oa-ob-actions').hidden=true;var s=m.querySelector('.oa-ob-stage');s.hidden=false;s.innerHTML=html;return s;}
function backButton(s){var b=s.querySelector('[data-back]');if(b)b.onclick=function(){wipe();open();};}
async function showCreate(){
  var s=stage('<button class="oa-ob-back" data-back>← Back</button><h3>Create New Wallet</h3><div class="oa-ob-loading">Generating securely…</div>');backButton(s);
  try{
    var tr=await makeTransport();
    var envelope=await post('/api/onboarding/wallet/create',{transport_key:tr.b64});
    var d=await openSealed(envelope,tr.raw);tr.raw.fill(0);generated=d;
    s.innerHTML='<button class="oa-ob-back" data-back>← Back</button><h3>Back up your private keys</h3><div class="oa-ob-warning">These keys control your funds. Save them somewhere safe now. OrcAgent will not show them again after activation.</div><label>Solana address</label><div class="oa-ob-address">'+esc(d.solana_address)+'</div><label>Solana private key</label><textarea class="oa-ob-secret" id="oa-ob-sol" readonly>'+esc(d.solana_private_key)+'</textarea><label>EVM address</label><div class="oa-ob-address">'+esc(d.evm_address)+'</div><label>EVM private key</label><textarea class="oa-ob-secret" id="oa-ob-evm" readonly>'+esc(d.evm_private_key)+'</textarea><label class="oa-ob-check"><input type="checkbox" id="oa-ob-confirm"> I saved both private keys safely.</label><button class="oa-ob-primary oa-ob-finish" id="oa-ob-activate" disabled>Activate Wallet</button><div class="oa-ob-msg" id="oa-ob-msg"></div>';
    backButton(s);var c=s.querySelector('#oa-ob-confirm'),a=s.querySelector('#oa-ob-activate');c.onchange=function(){a.disabled=!c.checked;};a.onclick=activate;
  }catch(e){s.innerHTML='<button class="oa-ob-back" data-back>← Back</button><div class="oa-ob-msg bad">'+esc(e.message)+'</div>';backButton(s);}
}
async function activate(){var a=document.getElementById('oa-ob-activate'),msg=document.getElementById('oa-ob-msg');a.disabled=true;a.textContent='Activating…';try{await post('/api/onboarding/wallet/confirm',{solana_private_key:generated.solana_private_key,evm_private_key:generated.evm_private_key,backup_confirmed:true});wipe();try{localStorage.removeItem('orca_manual_disconnect');}catch(_){}location.href='/';}catch(e){msg.textContent=e.message;msg.className='oa-ob-msg bad';a.disabled=false;a.textContent='Activate Wallet';}}
function showImport(){var s=stage('<button class="oa-ob-back" data-back>← Back</button><h3>Import Existing Wallet</h3><p class="oa-ob-sub">Paste your Solana private key. Optionally add an existing EVM private key; otherwise OrcAgent creates a new EVM wallet for BSC, Base, Arbitrum, Polygon and Robinhood Chain.</p><label>Solana private key</label><textarea class="oa-ob-secret" id="oa-import-sol" placeholder="Base58 private key"></textarea><label>EVM private key <small>(optional)</small></label><textarea class="oa-ob-secret" id="oa-import-evm" placeholder="0x…"></textarea><button class="oa-ob-primary oa-ob-finish" id="oa-import-go">Import Wallet</button><div class="oa-ob-msg" id="oa-import-msg"></div>');backButton(s);s.querySelector('#oa-import-go').onclick=doImport;}
async function doImport(){
  var b=document.getElementById('oa-import-go'),msg=document.getElementById('oa-import-msg');
  var sol=document.getElementById('oa-import-sol').value.trim(),evm=document.getElementById('oa-import-evm').value.trim();
  if(!sol){msg.textContent='Enter your Solana private key.';msg.className='oa-ob-msg bad';return;}
  b.disabled=true;b.textContent='Importing…';
  try{
    var payload={solana_private_key:sol,evm_private_key:evm},tr=null;
    if(!evm){tr=await makeTransport();payload.transport_key=tr.b64;}
    var d=await post('/api/onboarding/wallet/import',payload);
    if(tr){d=await openSealed(d,tr.raw);tr.raw.fill(0);}
    document.getElementById('oa-import-sol').value='';document.getElementById('oa-import-evm').value='';
    if(d.needs_confirmation&&d.evm_private_key){
      generated={solana_private_key:sol,evm_private_key:d.evm_private_key};
      var s=stage('<h3>Save your new EVM private key</h3><div class="oa-ob-warning">Your Solana wallet is ready to import. OrcAgent created one EVM wallet for the supported EVM chains. Save this key before activation.</div><div class="oa-ob-address">'+esc(d.evm_address)+'</div><textarea class="oa-ob-secret" readonly>'+esc(d.evm_private_key)+'</textarea><label class="oa-ob-check"><input type="checkbox" id="oa-import-confirm"> I saved this EVM private key safely.</label><button class="oa-ob-primary oa-ob-finish" id="oa-import-done" disabled>Activate Imported Wallet</button><div class="oa-ob-msg" id="oa-import-final-msg"></div>');
      var c=s.querySelector('#oa-import-confirm'),done=s.querySelector('#oa-import-done');c.onchange=function(){done.disabled=!c.checked;};
      done.onclick=async function(){var fm=document.getElementById('oa-import-final-msg');done.disabled=true;done.textContent='Activating…';try{await post('/api/onboarding/wallet/confirm',{solana_private_key:generated.solana_private_key,evm_private_key:generated.evm_private_key,backup_confirmed:true});wipe();try{localStorage.removeItem('orca_manual_disconnect');}catch(_){}location.href='/';}catch(e){fm.textContent=e.message;fm.className='oa-ob-msg bad';done.disabled=false;done.textContent='Activate Imported Wallet';}};
    }else{try{localStorage.removeItem('orca_manual_disconnect');}catch(_){}location.href='/';}
  }catch(e){msg.textContent=e.message;msg.className='oa-ob-msg bad';b.disabled=false;b.textContent='Import Wallet';}
}
document.addEventListener('click',function(e){
  var t=e.target&&e.target.closest?e.target.closest('#oa-guest-connect-btn,.pt-nb-profile-link[data-oa-auth="guest"],#guest-banner .gb-link,.gb-link'):null;
  if(!t||bypass)return;
  e.preventDefault();e.stopPropagation();e.stopImmediatePropagation();open();
},true);
window.OrcAgentWalletOnboarding={open:open};
})();
