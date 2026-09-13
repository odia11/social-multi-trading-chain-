/* Reliable guest Connect Wallet button for mobile OrcAgent Home. */
(function(){
'use strict';
if((location.pathname.replace(/\/+$/,'')||'/')!=='/' || !window.matchMedia('(max-width:767px)').matches)return;
var checking=false,last=0,INTERVAL=15000;
function startConnect(){
  var b=document.getElementById('phantom-ob-btn');
  if(b){try{b.click();return true}catch(_){}}
  if(typeof window.connectWalletOnboard==='function'){try{window.connectWalletOnboard('phantom');return true}catch(_){}}
  if(typeof window.connectWallet==='function'){try{window.connectWallet();return true}catch(_){}}
  return false;
}
function remove(){var b=document.getElementById('oa-guest-connect-btn');if(b)b.remove()}
function show(){
  var root=document.querySelector('.pt-nb-topbar');if(!root)return;
  if(document.getElementById('oa-guest-connect-btn'))return;
  root.style.position='relative';
  var profile=root.querySelector('.pt-nb-profile-link');if(profile)profile.style.display='none';
  var btn=document.createElement('button');btn.id='oa-guest-connect-btn';btn.type='button';btn.setAttribute('aria-label','Connect Wallet');
  btn.innerHTML='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h13a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h12"/><path d="M16 12h5v4h-5a2 2 0 0 1 0-4z"/></svg><span>Connect</span>';
  btn.style.cssText='position:absolute;right:10px;top:50%;transform:translateY(-50%);z-index:10000;height:44px;min-width:112px;padding:0 14px;border:0;border-radius:14px;background:#f7b955;color:#080d12;display:flex;align-items:center;justify-content:center;gap:7px;font:800 14px/1 system-ui,-apple-system,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.35);cursor:pointer;-webkit-tap-highlight-color:transparent';
  btn.addEventListener('click',function(e){e.preventDefault();e.stopPropagation();if(startConnect())return;try{sessionStorage.setItem('orca-open-connect','1')}catch(_){}location.href='/'});
  root.appendChild(btn);
}
function user(){remove();var root=document.querySelector('.pt-nb-topbar'),profile=root&&root.querySelector('.pt-nb-profile-link');if(profile)profile.style.display=''}
function sync(force){var now=Date.now();if(checking||(!force&&now-last<INTERVAL))return;checking=true;last=now;fetch('/api/me',{credentials:'include',cache:'no-store'}).then(function(r){if(r.status===429)return null;if(!r.ok)throw new Error('guest');return r.json()}).then(function(d){if(d===null)return;if(d&&d.ok)user();else show()}).catch(show).finally(function(){checking=false})}
function boot(){show();sync(true);setTimeout(show,250);setTimeout(show,1000)}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
window.addEventListener('pageshow',function(){show();sync(false)});
document.addEventListener('visibilitychange',function(){if(!document.hidden){show();sync(false)}});
})();
