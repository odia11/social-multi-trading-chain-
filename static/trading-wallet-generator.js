(function(){
'use strict';

var generated=null;

function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
function post(url,body){
  if(typeof window._post==='function') return window._post(url,body);
  var csrf=(typeof window._csrf==='string'?window._csrf:'');
  return fetch(url,{method:'POST',credentials:'include',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body||{})}).then(function(r){return r.json();});
}
function copyText(text,btn){
  if(!text)return;
  var done=function(){if(btn){var old=btn.textContent;btn.textContent='Copied';setTimeout(function(){btn.textContent=old;},1000);}};
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text).then(done).catch(function(){});return;}
  var t=document.createElement('textarea');t.value=text;t.style.position='fixed';t.style.opacity='0';document.body.appendChild(t);t.select();try{document.execCommand('copy');done();}catch(e){}t.remove();
}
function setStatus(text,bad){var el=document.getElementById('oa-gen-status');if(!el)return;el.textContent=text||'';el.className='oa-gen-status'+(bad?' bad':'');}
function wipe(){
  if(generated){generated.solana_private_key='';generated.evm_private_key='';generated=null;}
  ['oa-gen-sol-key','oa-gen-evm-key'].forEach(function(id){var el=document.getElementById(id);if(el)el.value='';});
}
function reveal(id,btn){var el=document.getElementById(id);if(!el)return;var hidden=el.type==='password';el.type=hidden?'text':'password';btn.textContent=hidden?'Hide':'Reveal';}

async function generate(){
  var btn=document.getElementById('oa-generate-wallet');
  if(!btn)return;
  if(generated&&!confirm('A generated wallet is already shown. Generating again will discard it unless you saved the keys. Continue?'))return;
  wipe();
  btn.disabled=true;btn.textContent='Generating…';setStatus('',false);
  try{
    var d=await post('/api/wallet/generate-trading-wallet',{});
    if(!d||!d.ok||!d.solana_private_key||!d.evm_private_key){throw new Error((d&&(d.error||d.msg))||'Could not generate wallet');}
    generated=d;
    document.getElementById('oa-gen-sol-addr').textContent=d.solana_address||'—';
    document.getElementById('oa-gen-evm-addr').textContent=d.evm_address||'—';
    document.getElementById('oa-gen-sol-key').value=d.solana_private_key;
    document.getElementById('oa-gen-evm-key').value=d.evm_private_key;
    document.getElementById('oa-gen-confirm').checked=false;
    document.getElementById('oa-gen-save').disabled=true;
    document.getElementById('oa-gen-panel').hidden=false;
    setStatus('Wallet created. Save both private keys before continuing.',false);
  }catch(e){setStatus(e.message||'Could not generate wallet',true);}
  finally{btn.disabled=false;btn.textContent='Generate New Trading Wallet';}
}

async function saveGenerated(){
  if(!generated){setStatus('Generate a wallet first.',true);return;}
  var check=document.getElementById('oa-gen-confirm');
  if(!check||!check.checked){setStatus('Confirm that you saved both private keys first.',true);return;}
  var btn=document.getElementById('oa-gen-save');btn.disabled=true;btn.textContent='Saving securely…';
  try{
    var d=await post('/api/wallet/generated/confirm',{
      solana_private_key:generated.solana_private_key,
      evm_private_key:generated.evm_private_key,
      backup_confirmed:true
    });
    if(!d||!d.ok)throw new Error((d&&(d.error||d.msg))||'Could not save wallet');
    setStatus('✓ Trading wallets saved and encrypted. You are ready to trade.',false);
    wipe();
    document.getElementById('oa-gen-confirm').checked=false;
    setTimeout(function(){window.location.reload();},900);
  }catch(e){setStatus(e.message||'Could not save wallet',true);btn.disabled=false;btn.textContent='Save & Enable Trading';}
}

function build(){
  var modal=document.getElementById('manage-modal');
  if(!modal||document.getElementById('oa-generate-wallet'))return;
  var box=modal.querySelector('.modal-box');if(!box)return;
  var title=box.querySelector('.modal-title');
  var wrap=document.createElement('div');wrap.className='oa-gen-wrap';
  wrap.innerHTML='\
    <div class="oa-gen-choice">\
      <div class="oa-gen-choice-copy"><strong>New to crypto?</strong><span>Create a dedicated OrcAgent trading wallet for Solana + all EVM chains.</span></div>\
      <button type="button" class="oa-gen-btn" id="oa-generate-wallet">Generate New Trading Wallet</button>\
    </div>\
    <div class="oa-gen-or"><span>or import an existing Solana trading key below</span></div>\
    <div class="oa-gen-panel" id="oa-gen-panel" hidden>\
      <div class="oa-gen-alert"><strong>Back these up now.</strong> These private keys are shown for this setup only. Anyone with them can control the funds in these trading wallets.</div>\
      <div class="oa-gen-block"><label>Solana trading address</label><div class="oa-gen-address"><span id="oa-gen-sol-addr">—</span></div><label>Solana private key</label><div class="oa-gen-keyrow"><input id="oa-gen-sol-key" type="password" readonly autocomplete="off"><button type="button" data-reveal="oa-gen-sol-key">Reveal</button><button type="button" data-copy="sol">Copy</button></div></div>\
      <div class="oa-gen-block"><label>EVM trading address <small>BSC · Base · Arbitrum · Polygon</small></label><div class="oa-gen-address"><span id="oa-gen-evm-addr">—</span></div><label>EVM private key</label><div class="oa-gen-keyrow"><input id="oa-gen-evm-key" type="password" readonly autocomplete="off"><button type="button" data-reveal="oa-gen-evm-key">Reveal</button><button type="button" data-copy="evm">Copy</button></div></div>\
      <label class="oa-gen-check"><input id="oa-gen-confirm" type="checkbox"><span>I saved both private keys somewhere safe. I understand OrcAgent cannot protect funds if somebody gets these keys.</span></label>\
      <button type="button" class="oa-gen-save" id="oa-gen-save" disabled>Save & Enable Trading</button>\
      <div class="oa-gen-status" id="oa-gen-status"></div>\
    </div>';
  if(title&&title.nextSibling)box.insertBefore(wrap,title.nextSibling);else box.insertBefore(wrap,box.firstChild);

  document.getElementById('oa-generate-wallet').addEventListener('click',generate);
  document.getElementById('oa-gen-save').addEventListener('click',saveGenerated);
  document.getElementById('oa-gen-confirm').addEventListener('change',function(){document.getElementById('oa-gen-save').disabled=!this.checked;});
  wrap.addEventListener('click',function(e){
    var rb=e.target.closest('[data-reveal]');if(rb){reveal(rb.getAttribute('data-reveal'),rb);return;}
    var cb=e.target.closest('[data-copy]');if(cb){copyText(cb.getAttribute('data-copy')==='sol'?(generated&&generated.solana_private_key):(generated&&generated.evm_private_key),cb);}
  });

  // If the existing modal closes, drop any generated plaintext from our JS state.
  var close=box.querySelector('.modal-close');if(close)close.addEventListener('click',wipe);
  modal.addEventListener('click',function(e){if(e.target===modal)wipe();});
}

if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',build);else build();
window.addEventListener('pagehide',wipe);
})();
