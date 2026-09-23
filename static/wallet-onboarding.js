(function(){
'use strict';
var generated=null;
var AAD='orcagent-wallet-onboarding-v1';
var EVM_ORDER=BigInt('0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141');
var ICON_COPY='<svg class="oa-ob-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="8" y="8" width="11" height="11" rx="2" stroke="currentColor" stroke-width="1.8"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" stroke="currentColor" stroke-width="1.8"/></svg>';
var ICON_EYE='<svg class="oa-ob-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M2.5 12s3.4-6 9.5-6 9.5 6 9.5 6-3.4 6-9.5 6-9.5-6-9.5-6Z" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="12" r="2.7" stroke="currentColor" stroke-width="1.8"/></svg>';
var ICON_EYE_OFF='<svg class="oa-ob-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m3 3 18 18M10.6 6.1c.45-.07.92-.1 1.4-.1 6.1 0 9.5 6 9.5 6a16 16 0 0 1-2.2 2.8M6.2 7.3A15.2 15.2 0 0 0 2.5 12s3.4 6 9.5 6c1.2 0 2.3-.23 3.3-.6M9.9 9.9a3 3 0 0 0 4.2 4.2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
var ICON_SHIELD='<svg class="oa-ob-shield" viewBox="0 0 32 36" fill="none" aria-hidden="true"><path d="M16 2.5 28 7v9.2c0 8-5 13.5-12 17.3C9 29.7 4 24.2 4 16.2V7l12-4.5Z" stroke="currentColor" stroke-width="2"/><path d="M16 10v9M16 24h.01" stroke="currentColor" stroke-width="2.3" stroke-linecap="round"/></svg>';
var ICON_LOCK='<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="5" y="10" width="14" height="10" rx="2" stroke="currentColor" stroke-width="1.8"/><path d="M8 10V7a4 4 0 0 1 8 0v3" stroke="currentColor" stroke-width="1.8"/></svg>';
var ICON_WALLET_PLUS='<svg class="oa-ob-option-svg" viewBox="0 0 28 28" fill="none" aria-hidden="true"><path d="M5 8.5h15.5a2.5 2.5 0 0 1 2.5 2.5v11H6.5A2.5 2.5 0 0 1 4 19.5v-13A2.5 2.5 0 0 1 6.5 4H19v4.5" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M19 17h7M22.5 13.5v7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
var ICON_IMPORT='<svg class="oa-ob-option-svg" viewBox="0 0 28 28" fill="none" aria-hidden="true"><path d="M5 11h18v12H5z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M14 3v12m-4-4 4 4 4-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
var ICON_PHANTOM='<svg class="oa-ob-option-svg" viewBox="0 0 28 28" fill="none" aria-hidden="true"><path d="M5.2 20.9c1.8 1.7 4.1.5 5.4-1.1.7 2.1 3.1 2.2 4.6.2.9 1.3 3 1 4-.7 2.1-3.4 2.7-10.8-1.4-13.8C14.2 2.8 8.7 5.2 7 9.8c-1.4 3.8-3.2 9.2-1.8 11.1Z" fill="currentColor"/><circle cx="13.2" cy="11.4" r="1.2" fill="#0b1117"/><circle cx="17.4" cy="11.4" r="1.2" fill="#0b1117"/></svg>';
var ICON_CHEVRON='<svg class="oa-ob-chevron" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m9 5 7 7-7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
var ICON_TRUST='<svg class="oa-ob-trust-icon" viewBox="0 0 24 26" fill="none" aria-hidden="true"><path d="M12 2 21 5.4v6.9c0 6-3.8 10.2-9 13-5.2-2.8-9-7-9-13V5.4L12 2Z" stroke="currentColor" stroke-width="1.8"/><path d="m8.2 13 2.4 2.4 5.5-5.7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';

function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]);});}
function bytesToB64(bytes){var s='';for(var i=0;i<bytes.length;i++)s+=String.fromCharCode(bytes[i]);return btoa(s);}
function bytesToHex(bytes){return Array.prototype.map.call(bytes,function(b){return b.toString(16).padStart(2,'0');}).join('');}
function shortValue(value){var s=String(value||'');return s.length>22?s.slice(0,12)+'…'+s.slice(-10):s;}
function base58(bytes){
  var alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
  if(!bytes||!bytes.length)return '';
  var digits=[0];
  for(var i=0;i<bytes.length;i++){var carry=bytes[i];for(var j=0;j<digits.length;j++){var x=digits[j]*256+carry;digits[j]=x%58;carry=(x/58)|0;}while(carry){digits.push(carry%58);carry=(carry/58)|0;}}
  var out='';for(var z=0;z<bytes.length-1&&bytes[z]===0;z++)out+='1';for(var k=digits.length-1;k>=0;k--)out+=alphabet[digits[k]];return out;
}
function freshEvmKey(){var raw;do{raw=crypto.getRandomValues(new Uint8Array(32));}while(BigInt('0x'+bytesToHex(raw))===0n||BigInt('0x'+bytesToHex(raw))>=EVM_ORDER);var key='0x'+bytesToHex(raw);raw.fill(0);return key;}
function createLocalWallet(){
  if(!window.crypto||!crypto.subtle||!crypto.getRandomValues)throw new Error('Secure browser crypto is not available');
  if(!window.nacl||!nacl.sign||!nacl.sign.keyPair)throw new Error('Secure wallet library is still loading. Try again.');
  var kp=nacl.sign.keyPair();var wallet={solana_address:base58(kp.publicKey),solana_private_key:base58(kp.secretKey),evm_private_key:freshEvmKey()};kp.secretKey.fill(0);return wallet;
}
async function csrf(){if(window._csrfToken)return window._csrfToken;if(window._csrf)return window._csrf;try{var r=await fetch('/api/csrf',{credentials:'include',cache:'no-store'});var d=await r.json();return d.csrf_token||d.csrf||'';}catch(_){return '';}}
async function post(url,body){var t=await csrf();var r=await fetch(url,{method:'POST',credentials:'include',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':t},body:JSON.stringify(body||{})});var d={};try{d=await r.json();}catch(_){}if(!r.ok||!d.ok)throw new Error((d.error&&d.error.message)||d.error||'Request failed');return d;}
async function seal(payload){var raw=crypto.getRandomValues(new Uint8Array(32));var nonce=crypto.getRandomValues(new Uint8Array(12));var key=await crypto.subtle.importKey('raw',raw,{name:'AES-GCM'},false,['encrypt']);var plain=new TextEncoder().encode(JSON.stringify(payload));var encrypted=await crypto.subtle.encrypt({name:'AES-GCM',iv:nonce,additionalData:new TextEncoder().encode(AAD),tagLength:128},key,plain);var envelope={transport_key:bytesToB64(raw),nonce:bytesToB64(nonce),sealed:bytesToB64(new Uint8Array(encrypted)),alg:'A256GCM'};raw.fill(0);plain.fill(0);return envelope;}
async function securePost(url,payload){return post(url,await seal(payload));}
// Start Phantom's signed login directly. This used to "click" whichever
// guest connect control was on the page -- but once Phantom silently
// reconnects to a site it already trusts, the header drops its Connect
// button, the only control left is the guest banner's link, and that link
// just reopens this sheet: the click did nothing at all, Phantom was never
// asked. connectWalletOnboard lives in dashboard.js, which only some pages
// load; elsewhere hand off to the home page's existing phantom_connect
// auto-start, which returns here once signed in.
function connectPhantom(){
  close();
  if(typeof window.connectWalletOnboard==='function'){window.connectWalletOnboard('phantom');return;}
  location.href='/?phantom_connect=1&return_to='+encodeURIComponent(location.pathname+location.search);
}
function modal(){
  var m=document.getElementById('oa-wallet-onboarding');if(m)return m;
  m=document.createElement('div');m.id='oa-wallet-onboarding';m.className='oa-ob-backdrop';
  m.innerHTML='<div class="oa-ob-card" role="dialog" aria-modal="true" aria-label="Wallet setup"><div class="oa-ob-handle"></div><button class="oa-ob-close" aria-label="Close">×</button><div class="oa-ob-intro"><div class="oa-ob-brand">ORCAGENT</div><h2>Set up your wallet</h2><p class="oa-ob-sub">Choose how you want to continue.</p><div class="oa-ob-trust">'+ICON_TRUST+'<span>Self-custodial <b>•</b> Your keys, your funds</span></div></div><div class="oa-ob-actions"><button class="oa-ob-option oa-ob-option-featured" data-action="create"><span class="oa-ob-option-icon">'+ICON_WALLET_PLUS+'</span><span class="oa-ob-option-copy"><span class="oa-ob-option-title">Create new wallet <em>RECOMMENDED</em></span><span class="oa-ob-option-sub">Generate securely on this device.</span></span>'+ICON_CHEVRON+'</button><button class="oa-ob-option" data-action="import"><span class="oa-ob-option-icon">'+ICON_IMPORT+'</span><span class="oa-ob-option-copy"><span class="oa-ob-option-title">Import existing wallet</span><span class="oa-ob-option-sub">Use your Solana private key.</span></span>'+ICON_CHEVRON+'</button><button class="oa-ob-option" data-action="phantom"><span class="oa-ob-option-icon oa-ob-option-phantom">'+ICON_PHANTOM+'</span><span class="oa-ob-option-copy"><span class="oa-ob-option-title">Connect Phantom</span><span class="oa-ob-option-sub">Continue with your Phantom app.</span></span>'+ICON_CHEVRON+'</button></div><div class="oa-ob-chooser-foot">'+ICON_LOCK+'<span>Secure connection <b>•</b> Keys are never exposed</span></div><div class="oa-ob-stage" hidden></div></div>';
  document.body.appendChild(m);m.querySelector('.oa-ob-close').onclick=close;
  m.addEventListener('click',function(e){if(e.target===m)close();var b=e.target.closest('[data-action]');if(!b)return;if(b.dataset.action==='create')showCreate();if(b.dataset.action==='import')showImport();if(b.dataset.action==='phantom')connectPhantom();});
  return m;
}
function open(){var m=modal();m.style.display='flex';m.querySelector('.oa-ob-card').scrollTop=0;m.querySelector('.oa-ob-intro').hidden=false;m.querySelector('.oa-ob-actions').hidden=false;var s=m.querySelector('.oa-ob-stage');s.hidden=true;s.innerHTML='';}
function close(){var m=document.getElementById('oa-wallet-onboarding');if(m)m.style.display='none';wipe();}
function wipe(){if(generated){generated.solana_private_key='';generated.evm_private_key='';generated=null;}document.querySelectorAll('.oa-ob-secret,.oa-ob-secret-input').forEach(function(x){x.value='';});}
function stage(html){var m=modal();m.querySelector('.oa-ob-intro').hidden=true;m.querySelector('.oa-ob-actions').hidden=true;var s=m.querySelector('.oa-ob-stage');s.hidden=false;s.innerHTML=html;m.querySelector('.oa-ob-card').scrollTop=0;return s;}
function backButton(s){var b=s.querySelector('[data-back]');if(b)b.onclick=function(){wipe();open();};}
function progress(){return '<div class="oa-ob-progress" aria-label="Step 2 of 3"><div class="oa-ob-step done"><span class="oa-ob-step-dot">✓</span><span>1 Create</span></div><span class="oa-ob-progress-line"></span><div class="oa-ob-step active"><span class="oa-ob-step-dot">2</span><span>2 Backup</span></div><span class="oa-ob-progress-line"></span><div class="oa-ob-step"><span class="oa-ob-step-dot">3</span><span>3 Activate</span></div></div>';}
function secretCard(label,id,keyName){
  return '<div class="oa-ob-field-card"><span class="oa-ob-field-label">'+label+'</span><div class="oa-ob-value-row"><div class="oa-ob-value"><input class="oa-ob-secret-input" id="'+id+'" type="password" readonly autocomplete="off" spellcheck="false"></div><button class="oa-ob-show-btn" type="button" data-show="'+id+'" aria-label="Show '+label.toLowerCase()+'">'+ICON_EYE+'<span>Show</span></button><button class="oa-ob-icon-btn" type="button" data-copy="'+keyName+'" aria-label="Copy '+label.toLowerCase()+'">'+ICON_COPY+'</button></div></div>';
}
function backupShell(address){
  return '<button class="oa-ob-back" data-back>← Back</button><div class="oa-ob-hero"><div class="oa-ob-brand">ORCAGENT</div><h3>Secure your wallet</h3><p class="oa-ob-sub">Back up both keys before activation.</p></div>'+progress()+'<div class="oa-ob-warning">'+ICON_SHIELD+'<span>Save these keys somewhere safe. They cannot be recovered after you leave this screen.</span></div><div class="oa-ob-fields"><div class="oa-ob-field-card"><span class="oa-ob-field-label">SOLANA ADDRESS</span><div class="oa-ob-value-row"><div class="oa-ob-value oa-ob-value-text">'+esc(shortValue(address))+'</div><button class="oa-ob-icon-btn" type="button" data-copy="solana_address" aria-label="Copy Solana address">'+ICON_COPY+'</button></div></div>'+secretCard('SOLANA PRIVATE KEY','oa-ob-sol','solana_private_key')+secretCard('EVM PRIVATE KEY','oa-ob-evm','evm_private_key')+'</div><div class="oa-ob-security-note">'+ICON_LOCK+'<span>Never share your private keys with anyone.</span></div><label class="oa-ob-check"><input type="checkbox" id="oa-ob-confirm"><span class="oa-ob-checkbox"></span><span>I saved both private keys securely.</span></label><button class="oa-ob-primary oa-ob-finish" id="oa-ob-activate" disabled>Activate wallet</button><div class="oa-ob-lock-note">'+ICON_LOCK+'<span>Encrypted during activation</span></div><div class="oa-ob-msg" id="oa-ob-msg"></div>';
}
function valueFor(name){return generated&&Object.prototype.hasOwnProperty.call(generated,name)?String(generated[name]||''):'';}
async function copyValue(name,button){
  var value=valueFor(name);if(!value)return;
  try{
    if(navigator.clipboard&&window.isSecureContext)await navigator.clipboard.writeText(value);
    else{var t=document.createElement('textarea');t.value=value;t.style.position='fixed';t.style.opacity='0';document.body.appendChild(t);t.select();document.execCommand('copy');t.remove();}
    button.classList.add('copied');button.innerHTML='<span aria-hidden="true">✓</span>';button.setAttribute('aria-label','Copied');
    setTimeout(function(){button.classList.remove('copied');button.innerHTML=ICON_COPY;button.setAttribute('aria-label','Copy');},1400);
  }catch(_){var msg=document.getElementById('oa-ob-msg')||document.getElementById('oa-import-final-msg');if(msg){msg.textContent='Could not copy. Press Show and copy the key manually.';msg.className='oa-ob-msg bad';}}
}
function bindSecureFields(s){
  s.querySelectorAll('[data-copy]').forEach(function(b){b.onclick=function(){copyValue(b.dataset.copy,b);};});
  s.querySelectorAll('[data-show]').forEach(function(b){b.onclick=function(){var input=document.getElementById(b.dataset.show);if(!input)return;var showing=input.type==='text';input.type=showing?'password':'text';b.innerHTML=(showing?ICON_EYE:ICON_EYE_OFF)+'<span>'+(showing?'Show':'Hide')+'</span>';b.setAttribute('aria-label',(showing?'Show ':'Hide ')+input.id);};});
}
function showCreate(){
  var s=stage('<button class="oa-ob-back" data-back>← Back</button><div class="oa-ob-hero"><div class="oa-ob-brand">ORCAGENT</div><h3>Creating your wallet</h3><p class="oa-ob-sub">Generating securely on this device…</p></div><div class="oa-ob-loading">Preparing encrypted wallet keys…</div>');backButton(s);
  try{
    var d=createLocalWallet();generated=d;s.innerHTML=backupShell(d.solana_address);
    s.querySelector('#oa-ob-sol').value=d.solana_private_key;s.querySelector('#oa-ob-evm').value=d.evm_private_key;
    backButton(s);bindSecureFields(s);var c=s.querySelector('#oa-ob-confirm'),a=s.querySelector('#oa-ob-activate');c.onchange=function(){a.disabled=!c.checked;};a.onclick=activate;
  }catch(e){s.innerHTML='<button class="oa-ob-back" data-back>← Back</button><div class="oa-ob-msg bad">'+esc(e.message)+'</div>';backButton(s);}
}
async function activate(){var a=document.getElementById('oa-ob-activate'),msg=document.getElementById('oa-ob-msg');a.disabled=true;a.textContent='Activating…';try{await securePost('/api/onboarding/wallet/confirm',{solana_private_key:generated.solana_private_key,evm_private_key:generated.evm_private_key,backup_confirmed:true});wipe();try{localStorage.removeItem('orca_manual_disconnect');}catch(_){}location.href='/';}catch(e){msg.textContent=e.message;msg.className='oa-ob-msg bad';a.disabled=false;a.textContent='Activate wallet';}}
function showImport(){var s=stage('<button class="oa-ob-back" data-back>← Back</button><div class="oa-ob-hero"><div class="oa-ob-brand">ORCAGENT</div><h3>Import wallet</h3><p class="oa-ob-sub">Enter your existing Solana key. An EVM key is optional.</p></div><label>Solana private key</label><textarea class="oa-ob-secret" id="oa-import-sol" placeholder="Base58 private key" autocomplete="off" spellcheck="false"></textarea><label>EVM private key <small>(optional)</small></label><textarea class="oa-ob-secret" id="oa-import-evm" placeholder="0x…" autocomplete="off" spellcheck="false"></textarea><button class="oa-ob-primary oa-ob-finish" id="oa-import-go">Import wallet</button><div class="oa-ob-lock-note">'+ICON_LOCK+'<span>Encrypted during activation</span></div><div class="oa-ob-msg" id="oa-import-msg"></div>');backButton(s);s.querySelector('#oa-import-go').onclick=doImport;}
async function finishImport(sol,evm,button,msg){button.disabled=true;button.textContent='Activating…';try{await securePost('/api/onboarding/wallet/import',{solana_private_key:sol,evm_private_key:evm});wipe();try{localStorage.removeItem('orca_manual_disconnect');}catch(_){}location.href='/';}catch(e){msg.textContent=e.message;msg.className='oa-ob-msg bad';button.disabled=false;button.textContent='Import wallet';}}
async function doImport(){
  var b=document.getElementById('oa-import-go'),msg=document.getElementById('oa-import-msg');var sol=document.getElementById('oa-import-sol').value.trim(),evm=document.getElementById('oa-import-evm').value.trim();
  if(!sol){msg.textContent='Enter your Solana private key.';msg.className='oa-ob-msg bad';return;}if(evm)return finishImport(sol,evm,b,msg);
  evm=freshEvmKey();generated={solana_private_key:sol,evm_private_key:evm};document.getElementById('oa-import-sol').value='';document.getElementById('oa-import-evm').value='';
  var s=stage('<button class="oa-ob-back" data-back>← Back</button><div class="oa-ob-hero"><div class="oa-ob-brand">ORCAGENT</div><h3>Secure your EVM wallet</h3><p class="oa-ob-sub">Save this new key before activation.</p></div><div class="oa-ob-warning">'+ICON_SHIELD+'<span>This key was created securely on your device. It cannot be recovered later.</span></div><div class="oa-ob-fields">'+secretCard('EVM PRIVATE KEY','oa-import-generated-evm','evm_private_key')+'</div><div class="oa-ob-security-note">'+ICON_LOCK+'<span>Never share your private key with anyone.</span></div><label class="oa-ob-check"><input type="checkbox" id="oa-import-confirm"><span class="oa-ob-checkbox"></span><span>I saved this EVM private key securely.</span></label><button class="oa-ob-primary oa-ob-finish" id="oa-import-done" disabled>Activate imported wallet</button><div class="oa-ob-lock-note">'+ICON_LOCK+'<span>Encrypted during activation</span></div><div class="oa-ob-msg" id="oa-import-final-msg"></div>');
  s.querySelector('#oa-import-generated-evm').value=evm;backButton(s);bindSecureFields(s);var c=s.querySelector('#oa-import-confirm'),done=s.querySelector('#oa-import-done');c.onchange=function(){done.disabled=!c.checked;};done.onclick=function(){finishImport(generated.solana_private_key,generated.evm_private_key,done,document.getElementById('oa-import-final-msg'));};
}
document.addEventListener('click',function(e){var t=e.target&&e.target.closest?e.target.closest('#oa-guest-connect-btn,.pt-nb-profile-link[data-oa-auth="guest"],#guest-banner .gb-link,.gb-link'):null;if(!t)return;e.preventDefault();e.stopPropagation();e.stopImmediatePropagation();open();},true);
window.OrcAgentWalletOnboarding={open:open};
})();