/* OrcAgent client-side XSS defense-in-depth.
 * Server/output escaping remains the primary boundary. This guard neutralizes
 * dangerous URL schemes in dynamically inserted DOM and fixes one legacy
 * copy-trading modal that interpolated a username into innerHTML.
 */
(function(){
'use strict';

function unsafeUrl(v, attr){
  v=String(v||'').trim().replace(/[\u0000-\u001f\u007f\s]+/g,'').toLowerCase();
  if(!v)return false;
  if(v.indexOf('javascript:')===0||v.indexOf('vbscript:')===0)return true;
  if(v.indexOf('data:')===0){
    // OrcAgent legitimately renders image data URIs. Everything else is
    // blocked because data:text/html / data:image/svg+xml can become active
    // content in the wrong context.
    return !(attr==='src' && /^data:image\/(?:png|jpe?g|webp|gif);/i.test(v));
  }
  return false;
}

function scrub(root){
  if(!root||root.nodeType!==1)return;
  var nodes=[];
  if(root.matches&&root.matches('[href],[src],[action],[formaction]'))nodes.push(root);
  if(root.querySelectorAll)nodes=nodes.concat(Array.prototype.slice.call(root.querySelectorAll('[href],[src],[action],[formaction]')));
  nodes.forEach(function(el){
    ['href','src','action','formaction'].forEach(function(attr){
      if(!el.hasAttribute(attr))return;
      var value=el.getAttribute(attr)||'';
      if(unsafeUrl(value,attr)){
        el.removeAttribute(attr);
        el.setAttribute('data-orca-blocked-'+attr,'1');
      }
    });
    if(el.tagName==='A' && el.getAttribute('target')==='_blank'){
      var rel=(el.getAttribute('rel')||'').split(/\s+/).filter(Boolean);
      ['noopener','noreferrer'].forEach(function(x){if(rel.indexOf(x)<0)rel.push(x)});
      el.setAttribute('rel',rel.join(' '));
    }
  });
}

function safeCopyModal(){
  if(typeof window._openCopyModal!=='function')return;
  window._openCopyModal=function(wallet,username,userId,btn){
    if(typeof window._loggedIn!=='undefined' && !window._loggedIn){
      if(typeof window._toast==='function')window._toast('Connect your wallet to copy trades','err');
      return;
    }
    var isCopying=!!(btn&&btn.classList.contains('copying'));
    window._copyModal={wallet:wallet,userId:userId,btn:btn,stopping:isCopying};
    var user=document.getElementById('modal-username');if(user)user.textContent=String(username||'');
    var confirmBtn=document.getElementById('modal-confirm-btn');
    var amountField=document.getElementById('modal-amount-field');
    var desc=document.getElementById('modal-desc');
    if(!confirmBtn||!amountField||!desc)return;

    desc.replaceChildren();
    if(isCopying){
      desc.append(document.createTextNode('Stop copying '));
      var strong=document.createElement('strong');strong.textContent=String(username||'');desc.append(strong);
      desc.append(document.createTextNode('? No new trades will be mirrored.'));
      amountField.style.display='none';
      confirmBtn.textContent='Stop Copying';
      confirmBtn.className='modal-btn danger';
    }else{
      desc.append(document.createTextNode('When '));
      var strong2=document.createElement('strong');strong2.textContent=String(username||'');desc.append(strong2);
      desc.append(document.createTextNode(' opens a trade, you automatically mirror it with the amount below.'));
      amountField.style.display='';
      var inp=document.getElementById('modal-sol-inp');if(inp)inp.value='0.1';
      var hint=document.getElementById('modal-hint');if(hint)hint.textContent='Each mirrored trade will spend this amount of SOL.';
      confirmBtn.textContent='Start Copying';
      confirmBtn.className='modal-btn primary';
    }
    var backdrop=document.getElementById('copy-modal-backdrop');if(backdrop)backdrop.classList.add('open');
    if(!isCopying){var input=document.getElementById('modal-sol-inp');if(input)input.focus();}
  };
}

function boot(){
  scrub(document.documentElement);
  safeCopyModal();
  try{
    new MutationObserver(function(ms){ms.forEach(function(m){m.addedNodes.forEach(function(n){if(n.nodeType===1)scrub(n)})})})
      .observe(document.documentElement,{childList:true,subtree:true});
  }catch(_){ }
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
