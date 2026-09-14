(function(){
'use strict';
var generated=null,bypass=false;
var AAD='orcagent-wallet-onboarding-v1';
var EVM_ORDER=BigInt('0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141');

function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]);});}
function bytesToB64(bytes){var s='';for(var i=0;i<bytes.length;i++)s+=String.fromCharCode(bytes[i]);return btoa(s);}
function bytesToHex(bytes){return Array.prototype.map.call(bytes,function(b){return b.toString(16).padStart(2,'0');}).join('');}
function base58(bytes){
  var alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
  if(!bytes||!bytes.length)return '';
  var digits=[0];
  for(var i=0;i<bytes.length;i++){
    var carry=bytes[i];
    for(var j=0;j<digits.length;j++){var x=digits[j]*256+carry;digits[j]=x%58;carry=(x/58)|0;}
    while(carry){digits.push(carry%58);carry=(carry/58)|0;}
  }
  var out='';for(var z=0;z<bytes.length-1&&bytes[z]===0;z++)out+='1';
  for(var k=digits.length-1;k>=0;k--)out+=alphabet[digits[k]];
  return out;
}
function freshEvmKey(){
  var raw;
  do{raw=crypto.getRandomValues(new Uint8Array(32));}
  while(BigInt('0x'+bytesToHex(raw))===0n||BigInt('0x'+bytesToHex(raw))>=EVM_ORDER);
  var key='0x'+bytesToHex(raw);raw.fill(0);return key;
}
function createLocalWallet(){
  if(!window.crypto||!crypto.subtle||!crypto.getRandomValues)throw new Error('Secure browser crypto is not available');
  if(!window.nacl||!nacl.sign||!nacl.sign.keyPair)throw new Error('Secure wallet library is still loading. Try again.');
  var kp=nacl.sign.keyPair();
  var wallet={
    solana_address:base58(kp.publicKey),
    solana_private_key:base58(kp.secretKey),
    evm_private_key:freshEvmKey()
  };
  kp.secretKey.fill(0);return wallet;
}
async function csrf(){
  if(window._csrfToken)return window._csrfToken;
  if(window._csrf)return window._csrf;
  try{var r=await fetch('/api/csrf',{credentials:'include',cache:'no-store'});var d=await r.json();return d.csrf_token||d.csrf||'';}catch(_){return '';}
}
async function post(url,body){
  var t=await csrf();
  var r=await fetch(url,{method:'POST',credentials:'include',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':t},body:JSON.stringify(body||{})});
  var d={};try{d=await r.json();}catch(_){}
  if(!r.ok||!d.ok)throw new Error((d.error&&d.error.message)||d.error||'Request failed');
  return d;
}
async function seal(payload){
  var raw=crypto.getRandomValues(new Uint8Array(32));
  var nonce=crypto.getRandomValues(new Uint8Array(12));
  var key=await crypto.subtle.importKey('raw',raw,{name:'AES-GCM'},false,['encrypt']);
  var plain=new TextEncoder().encode(JSON.stringify(payload));
  var encrypted=await crypto.subtle.encrypt({name:'AES-GCM',iv:nonce,additionalData:new TextEncoder().encode(AAD),tagLength:128},key,plain);
  var envelope={transport_key:bytesToB64(raw),nonce:bytesToB64(nonce),sealed:bytesToB64(new Uint8Array(encrypted)),alg:'A256GCM'};
  raw.fill(0);plain.fill(0);return envelope;
}
async function securePost(url,payload){return post(url,await seal(payload));}
function connectControl(){return document.getElementById('oa-guest-connect-btn')||document.querySelector('.pt-nb-profile-link[data-oa-auth="guest"]')||document.querySelector('#guest-banner .gb-link,.gb-link');}
function modal(){
  var m=document.getElementById('oa-wallet-onboarding');if(m)return m;
  m=document.createElement('div');m.id='oa-wallet-onboarding';m.className='oa-ob-backdrop';
  m.innerHTML='<div class="oa-ob-card" role="dialog" aria-modal="true" aria-label="Wallet setup"><button class="oa-ob-close" aria-label="Close">×</button><div class="oa-ob-brand">ORCAGENT</div><h2>Set up your wallet</h2><p class="oa-ob-sub">Create a new OrcAgent wallet or use one you already own.</p><div class="oa-ob-actions"><button class="oa-ob-primary" data-action="create"><strong>Create New Wallet</strong><span>Generate a new self-custodial wallet and private keys.</span></button><button class="oa-ob-secondary" data-action="import"><strong>Import Existing Wallet</strong><span>Import with your Solana private key.</span></button><button class="oa-ob-secondary" data-action="phantom"><strong>Connect Phantom</strong><span>Use the wallet already in your Phantom app.</span></button></div><div class="oa-ob-stage" hidden></div></div>';
  document.body.appendChild(m);m.querySelector('.oa-ob-close').onclick=close;
  m.addEventListener('click',function(e){
    if(e.target===m)close();var b=e.target.closest('[data-action]');if(!b)return;
    if(b.dataset.action==='create')showCreate();
    if(b.dataset.action==='import')showImport();
    if(b.dataset.action==='phantom'){
      close();bypass=true;var x=connectControl();
      if(x){try{x.click();}catch(_){}}
      else if(typeof window.connectWalletOnboard==='function'){try{window.connectWalletOnboard('phantom');}catch(_){}}
      else if(typeof window.connectWallet==='function'){try{window.connectWallet();}catch(_){}}
      setTimeout(function(){bypass=false;},80);
    }
  });return m;
}
function open(){var m=modal();m.style.display='flex';var s=m.querySelector('.oa-ob-stage');s.hidden=true;s.innerHTML='';m.querySelector('.oa-ob-actions').hidden=false;}
function close(){var m=document.getElementById('oa-wallet-onboarding');if(m)m.style.display='none';wipe();}
function wipe(){if(generated){generated.solana_private_key='';generated.evm_private_key='';generated=null;}document.querySelectorAll('.oa-ob-secret').forEach(function(x){x.value='';});}
function stage(html){var m=modal();m.querySelector('.oa-ob-actions').hidden=true;var s=m.querySelector('.oa-ob-stage');s.hidden=false;s.innerHTML=html;return s;}
function backButton(s){var b=s.querySelector('[data-back]');if(b)b.onclick=function(){wipe();open();};}
function showCreate(){
  var s=stage('<button class="oa-ob-back" data-back>← Back</button><h3>Create New Wallet</h3><div class="oa-ob-loading">Generating securely on this device…</div>');backButton(s);
  try{
    var d=createLocalWallet();generated=d;
    s.innerHTML='<button class="oa-ob-back" data-back>← Back</button><h3>Back up your private keys</h3><div class="oa-ob-warning">These keys were created on this device. Save them somewhere safe now. OrcAgent will not show them again after activation.</div><label>Solana address</label><div class="oa-ob-address">'+esc(d.solana_address)+'</div><label>Solana private key</label><textarea class="oa-ob-secret" id="oa-ob-sol" readonly>'+esc(d.solana_private_key)+'</textarea><label>EVM private key</label><textarea class="oa-ob-secret" id="oa-ob-evm" readonly>'+esc(d.evm_private_key)+'</textarea><label class="oa-ob-check"><input type="checkbox" id="oa-ob-confirm"> I saved both private keys safely.</label><button class="oa-ob-primary oa-ob-finish" id="oa-ob-activate" disabled>Activate Wallet</button><div class="oa-ob-msg" id="oa-ob-msg"></div>';
    backButton(s);var c=s.querySelector('#oa-ob-confirm'),a=s.querySelector('#oa-ob-activate');c.onchange=function(){a.disabled=!c.checked;};a.onclick=activate;
  }catch(e){s.innerHTML='<button class="oa-ob-back" data-back>← Back</button><div class="oa-ob-msg bad">'+esc(e.message)+'</div>';backButton(s);}
}
async function activate(){
  var a=document.getElementById('oa-ob-activate'),msg=document.getElementById('oa-ob-msg');a.disabled=true;a.textContent='Activating…';
  try{
    await securePost('/api/onboarding/wallet/confirm',{solana_private_key:generated.solana_private_key,evm_private_key:generated.evm_private_key,backup_confirmed:true});
    wipe();try{localStorage.removeItem('orca_manual_disconnect');}catch(_){}location.href='/';
  }catch(e){msg.textContent=e.message;msg.className='oa-ob-msg bad';a.disabled=false;a.textContent='Activate Wallet';}
}
function showImport(){
  var s=stage('<button class="oa-ob-back" data-back>← Back</button><h3>Import Existing Wallet</h3><p class="oa-ob-sub">Paste your Solana private key. Optionally add an existing EVM private key; otherwise OrcAgent creates one securely on this device for BSC, Base, Arbitrum, Polygon and Robinhood Chain.</p><label>Solana private key</label><textarea class="oa-ob-secret" id="oa-import-sol" placeholder="Base58 private key"></textarea><label>EVM private key <small>(optional)</small></label><textarea class="oa-ob-secret" id="oa-import-evm" placeholder="0x…"></textarea><button class="oa-ob-primary oa-ob-finish" id="oa-import-go">Import Wallet</button><div class="oa-ob-msg" id="oa-import-msg"></div>');
  backButton(s);s.querySelector('#oa-import-go').onclick=doImport;
}
async function finishImport(sol,evm,button,msg){
  button.disabled=true;button.textContent='Activating…';
  try{
    await securePost('/api/onboarding/wallet/import',{solana_private_key:sol,evm_private_key:evm});
    wipe();try{localStorage.removeItem('orca_manual_disconnect');}catch(_){}location.href='/';
  }catch(e){msg.textContent=e.message;msg.className='oa-ob-msg bad';button.disabled=false;button.textContent='Import Wallet';}
}
async function doImport(){
  var b=document.getElementById('oa-import-go'),msg=document.getElementById('oa-import-msg');
  var sol=document.getElementById('oa-import-sol').value.trim(),evm=document.getElementById('oa-import-evm').value.trim();
  if(!sol){msg.textContent='Enter your Solana private key.';msg.className='oa-ob-msg bad';return;}
  if(evm){return finishImport(sol,evm,b,msg);}
  evm=freshEvmKey();generated={solana_private_key:sol,evm_private_key:evm};
  document.getElementById('oa-import-sol').value='';document.getElementById('oa-import-evm').value='';
  var s=stage('<button class="oa-ob-back" data-back>← Back</button><h3>Save your new EVM private key</h3><div class="oa-ob-warning">OrcAgent created this key securely on your device. Save it before activation.</div><textarea class="oa-ob-secret" readonly>'+esc(evm)+'</textarea><label class="oa-ob-check"><input type="checkbox" id="oa-import-confirm"> I saved this EVM private key safely.</label><button class="oa-ob-primary oa-ob-finish" id="oa-import-done" disabled>Activate Imported Wallet</button><div class="oa-ob-msg" id="oa-import-final-msg"></div>');
  backButton(s);var c=s.querySelector('#oa-import-confirm'),done=s.querySelector('#oa-import-done');c.onchange=function(){done.disabled=!c.checked;};
  done.onclick=function(){finishImport(generated.solana_private_key,generated.evm_private_key,done,document.getElementById('oa-import-final-msg'));};
}
document.addEventListener('click',function(e){
  var t=e.target&&e.target.closest?e.target.closest('#oa-guest-connect-btn,.pt-nb-profile-link[data-oa-auth="guest"],#guest-banner .gb-link,.gb-link'):null;
  if(!t||bypass)return;e.preventDefault();e.stopPropagation();e.stopImmediatePropagation();open();
},true);
window.OrcAgentWalletOnboarding={open:open};
})();