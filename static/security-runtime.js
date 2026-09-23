/* OrcAgent client-side XSS defense-in-depth.
 * Server/output escaping remains the primary boundary. This guard neutralizes
 * dangerous active URL schemes, strips srcdoc, normalizes URL-shaped API data
 * before legacy templates render it, and fixes the copy-trading username sink.
 */
(function(){
'use strict';

function compact(v){
  return String(v||'').trim().replace(/[\u0000-\u001f\u007f\s]+/g,'');
}

function unsafeUrl(v, attr){
  var raw=compact(v), low=raw.toLowerCase();
  if(!low)return false;
  if(low.indexOf('javascript:')===0||low.indexOf('vbscript:')===0)return true;
  if((attr==='href'||attr==='action'||attr==='formaction') && (low.indexOf('file:')===0||low.indexOf('filesystem:')===0))return true;
  if(low.indexOf('data:')===0){
    // OrcAgent legitimately renders raster image data URIs. SVG/HTML data
    // documents stay blocked because they can contain active content.
    return !(attr==='src' && /^data:image\/(?:png|jpe?g|webp|gif);/i.test(raw));
  }
  return false;
}

function scrub(root){
  if(!root||root.nodeType!==1)return;
  var nodes=[];
  if(root.matches&&root.matches('[href],[src],[action],[formaction],[srcdoc]'))nodes.push(root);
  if(root.querySelectorAll)nodes=nodes.concat(Array.prototype.slice.call(root.querySelectorAll('[href],[src],[action],[formaction],[srcdoc]')));
  nodes.forEach(function(el){
    if(el.hasAttribute('srcdoc')){
      el.removeAttribute('srcdoc');
      el.setAttribute('data-orca-blocked-srcdoc','1');
    }
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

function safeUrlValue(value){
  if(typeof value!=='string')return value;
  var raw=value.trim();
  if(!raw)return raw;
  if(raw.charAt(0)==='/' && raw.charAt(1)!=='/')return raw;
  if(/^blob:/i.test(raw))return raw;
  if(/^data:image\/(?:png|jpe?g|webp|gif);/i.test(raw))return raw;
  try{
    var u=new URL(raw,location.origin);
    if(u.protocol==='http:'||u.protocol==='https:')return u.href;
  }catch(_){ }
  return '';
}

function sanitizeApiJson(value, seen){
  if(value===null||value===undefined)return value;
  if(typeof value!=='object')return value;
  seen=seen||new WeakSet();
  if(seen.has(value))return value;
  seen.add(value);
  if(Array.isArray(value)){
    value.forEach(function(v,i){value[i]=sanitizeApiJson(v,seen)});
    return value;
  }
  Object.keys(value).forEach(function(k){
    var v=value[k], lk=String(k).toLowerCase();
    if(typeof v==='string' && (lk==='url'||lk==='href'||/_url$/.test(lk))){
      value[k]=safeUrlValue(v);
    }else if(v&&typeof v==='object'){
      value[k]=sanitizeApiJson(v,seen);
    }
  });
  return value;
}

function installApiJsonGuard(){
  if(!window.fetch||window.fetch.__orcaSecured)return;
  var original=window.fetch.bind(window);
  function guardedFetch(input,init){
    return original(input,init).then(function(response){
      try{
        var requested=(typeof input==='string')?input:(input&&input.url)||'';
        var u=new URL(requested,location.href);
        if(u.origin!==location.origin||u.pathname.indexOf('/api/')!==0)return response;
        var originalJson=response.json.bind(response);
        response.json=function(){return originalJson().then(function(data){return sanitizeApiJson(data)})};
      }catch(_){ }
      return response;
    });
  }
  guardedFetch.__orcaSecured=true;
  window.fetch=guardedFetch;
}

function installWindowOpenGuard(){
  if(!window.open||window.open.__orcaSecured)return;
  var original=window.open;
  function guardedOpen(url,target,features){
    var value=String(url==null?'':url);
    if(unsafeUrl(value,'href'))return null;
    var f=String(features||'');
    if(!target||target==='_blank'){
      if(!/(^|,)\s*noopener\s*(,|$)/i.test(f))f+=(f?',':'')+'noopener';
      if(!/(^|,)\s*noreferrer\s*(,|$)/i.test(f))f+=(f?',':'')+'noreferrer';
    }
    return original.call(window,value,target, f||undefined);
  }
  guardedOpen.__orcaSecured=true;
  window.open=guardedOpen;
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
      var inp=document.getElementById('modal-sol-inp');if(inp)inp.value='10';
      var hint=document.getElementById('modal-hint');if(hint)hint.textContent='Each mirrored trade will spend this amount of USDC.';
      confirmBtn.textContent='Start Copying';
      confirmBtn.className='modal-btn primary';
    }
    var backdrop=document.getElementById('copy-modal-backdrop');if(backdrop)backdrop.classList.add('open');
    if(!isCopying){var input=document.getElementById('modal-sol-inp');if(input)input.focus();}
  };
}

function boot(){
  scrub(document.documentElement);
  installApiJsonGuard();
  installWindowOpenGuard();
  safeCopyModal();
  try{
    new MutationObserver(function(ms){
      ms.forEach(function(m){
        if(m.type==='attributes')scrub(m.target);
        m.addedNodes.forEach(function(n){if(n.nodeType===1)scrub(n)});
      });
    }).observe(document.documentElement,{
      childList:true,subtree:true,attributes:true,
      attributeFilter:['href','src','action','formaction','srcdoc']
    });
  }catch(_){ }
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
