/* OrcAgent mobile auth control.
 *
 * Important rules:
 * - Never render Connect optimistically.
 * - The server session is authoritative when it says the user is signed in.
 * - A live/trusted Phantom provider also counts as connected while the server
 *   callback/recovery finishes.
 * - Only a confirmed guest state may render the Connect button.
 */
(function(){
'use strict';
if((location.pathname.replace(/\/+$/,'')||'/')!=='/' || !window.matchMedia('(max-width:767px)').matches)return;

var checking=false,last=0,INTERVAL=15000;

function provider(){
  if(window.phantom&&window.phantom.solana&&window.phantom.solana.isPhantom)return window.phantom.solana;
  if(window.solana&&window.solana.isPhantom)return window.solana;
  return null;
}
function providerConnected(){
  try{
    var p=provider();
    return !!(window.__ORCA_TRUSTED_PHANTOM_PUBLIC_KEY || (p&&p.isConnected&&p.publicKey));
  }catch(_){return !!window.__ORCA_TRUSTED_PHANTOM_PUBLIC_KEY;}
}
function startConnect(){
  var b=document.getElementById('phantom-ob-btn');
  if(b){try{b.click();return true}catch(_){}}
  if(typeof window.connectWalletOnboard==='function'){try{window.connectWalletOnboard('phantom');return true}catch(_){}}
  if(typeof window.connectWallet==='function'){try{window.connectWallet();return true}catch(_){}}
  return false;
}
function authOnlyEls(root){
  if(!root)return [];
  return Array.prototype.slice.call(root.querySelectorAll('a[href^="/messages"],a[href^="/notifications"]'));
}
function removeLegacyButtons(){
  ['oa-guest-connect-btn','oa-mobile-connect-wallet'].forEach(function(id){var b=document.getElementById(id);if(b)b.remove()});
}
function showUser(d){
  removeLegacyButtons();
  var root=document.querySelector('.pt-nb-topbar');
  if(!root)return;
  authOnlyEls(root).forEach(function(el){if(el.dataset.oaGuestHidden==='1'){el.style.display='';delete el.dataset.oaGuestHidden;}});
  var profile=root.querySelector('.pt-nb-profile-link');
  if(profile)profile.style.display='';
  if(d&&d.avatar){
    var img=document.getElementById('pt-nb-avatar'),ph=document.getElementById('pt-nb-avatar-ph');
    if(img){img.src=d.avatar;img.style.display='block';}
    if(ph)ph.style.display='none';
  }
}
function showGuest(){
  if(providerConnected()){showUser();return;}
  var root=document.querySelector('.pt-nb-topbar');if(!root)return;
  removeLegacyButtons();
  var profile=root.querySelector('.pt-nb-profile-link');if(profile)profile.style.display='none';
  /* Guests do not need DM/notification controls. Hiding those gives the
     Connect pill a real layout slot instead of overlaying the navbar. */
  authOnlyEls(root).forEach(function(el){el.dataset.oaGuestHidden='1';el.style.display='none';});
  var btn=document.createElement('button');btn.id='oa-guest-connect-btn';btn.type='button';btn.setAttribute('aria-label','Connect Wallet');
  btn.innerHTML='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h13a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h12"/><path d="M16 12h5v4h-5a2 2 0 0 1 0-4z"/></svg><span>Connect</span>';
  btn.style.cssText='height:44px;min-width:100px;padding:0 13px;border:0;border-radius:14px;background:#f7b955;color:#080d12;display:flex;align-items:center;justify-content:center;gap:7px;flex:0 0 auto;font:800 14px/1 system-ui,-apple-system,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.24);cursor:pointer;-webkit-tap-highlight-color:transparent';
  btn.addEventListener('click',function(e){e.preventDefault();e.stopPropagation();if(startConnect())return;try{sessionStorage.setItem('orca-open-connect','1')}catch(_){}location.href='/';});
  var profileSlot=root.querySelector('.pt-nb-profile-link');
  if(profileSlot&&profileSlot.parentNode===root)root.insertBefore(btn,profileSlot);
  else root.appendChild(btn);
}
function sync(force){
  if(providerConnected()){showUser();return;}
  var now=Date.now();if(checking||(!force&&now-last<INTERVAL))return;
  checking=true;last=now;
  fetch('/api/me',{credentials:'include',cache:'no-store'}).then(function(r){
    if(r.status===429)return {unknown:true};
    if(r.status===401||r.status===403)return {guest:true};
    if(!r.ok)return {unknown:true};
    return r.json();
  }).then(function(d){
    if(providerConnected()){showUser(d);return;}
    if(d&&d.ok){showUser(d);return;}
    if(d&&d.guest){showGuest();return;}
    if(d&&!d.ok&&!d.unknown){showGuest();return;}
    /* Network/rate-limit/temporary errors must never turn a connected-looking
       navbar into a guest navbar. */
  }).catch(function(){}).finally(function(){checking=false;});
}
function boot(){
  /* Remove stale buttons from older cached scripts, then ask the real auth
     state before deciding whether Connect belongs here. */
  removeLegacyButtons();
  if(providerConnected())showUser();
  sync(true);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
window.addEventListener('orca:phantom-trusted-connected',function(){showUser();setTimeout(function(){sync(true)},500);});
window.addEventListener('pageshow',function(){sync(true);});
document.addEventListener('visibilitychange',function(){if(!document.hidden)sync(true);});
window.addEventListener('online',function(){sync(true);});
try{
  var p=provider();
  if(p&&typeof p.on==='function'){
    p.on('connect',function(){showUser();setTimeout(function(){sync(true)},500);});
    p.on('disconnect',function(){setTimeout(function(){sync(true)},400);});
  }
}catch(_){}
/* Older cached home-mobile.js builds used a second absolute-position Connect
   button. Remove that stale element immediately if it is recreated so the
   header can never overlap again during cache transition. */
try{
  new MutationObserver(function(){
    var old=document.getElementById('oa-mobile-connect-wallet');
    if(old)old.remove();
  }).observe(document.documentElement,{childList:true,subtree:true});
}catch(_){}
})();
