/* OrcAgent shared navbar auth-state control.
   Logged out: the top-right profile slot becomes a Connect Wallet control.
   Logged in: restore the normal user profile avatar/link.
   The old full-screen onboarding gate is intentionally bypassed: Home is
   always browsable and the navbar connect control starts wallet connection. */
(function(){
'use strict';

var original=null;
var lastConnected=null;
var checkInFlight=false;
var lastCheckAt=0;
var MIN_CHECK_GAP_MS=15000;

function els(){
  var link=document.querySelector('.pt-nb-profile-link');
  if(!link)return null;
  return {link:link,img:document.getElementById('pt-nb-avatar'),ph:document.getElementById('pt-nb-avatar-ph')};
}

function remember(e){
  if(original||!e)return;
  original={html:e.link.innerHTML,href:e.link.getAttribute('href')||'',title:e.link.getAttribute('title')||'',aria:e.link.getAttribute('aria-label')||''};
}

function connectSvg(){
  return '<span class="pt-nb-connect-icon" aria-hidden="true" style="width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:rgba(247,185,85,.12);border:1px solid rgba(247,185,85,.5);color:#f7b955">'
    +'<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    +'<path d="M4 7h13a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h12"/>'
    +'<path d="M16 12h5v4h-5a2 2 0 0 1 0-4z"/><circle cx="17.5" cy="14" r=".5" fill="currentColor" stroke="none"/>'
    +'</svg></span>';
}

function revealHome(){
  var ob=document.getElementById('onboard');
  var app=document.getElementById('app');
  if(ob){ob.classList.add('hide');ob.style.display='none';ob.setAttribute('aria-hidden','true');}
  if(app)app.style.display='flex';
  try{if(typeof window.skipToApp==='function')window.skipToApp();}catch(_){}
  setTimeout(function(){if(ob){ob.classList.add('hide');ob.style.display='none';}if(app)app.style.display='flex';},0);
  setTimeout(function(){if(ob){ob.classList.add('hide');ob.style.display='none';}if(app)app.style.display='flex';},700);
}

function startWalletConnect(){
  if(typeof window.connectWalletOnboard==='function'){
    try{window.connectWalletOnboard('phantom');return true;}catch(_){}
  }
  if(typeof window.connectWallet==='function'){
    try{window.connectWallet();return true;}catch(_){}
  }
  return false;
}

function openConnect(e){
  if(e){e.preventDefault();e.stopPropagation();}
  revealHome();
  if(startWalletConnect())return false;
  try{sessionStorage.setItem('orca-open-connect','1');}catch(_){}
  if((location.pathname.replace(/\/+$/,'')||'/')!=='/')window.location.href='/';
  else setTimeout(startWalletConnect,250);
  return false;
}

function showGuest(){
  var e=els();if(!e)return;remember(e);
  lastConnected=false;
  e.link.removeAttribute('href');
  e.link.setAttribute('role','button');
  e.link.setAttribute('tabindex','0');
  e.link.setAttribute('title','Connect Wallet');
  e.link.setAttribute('aria-label','Connect Wallet');
  e.link.innerHTML=connectSvg();
  e.link.onclick=openConnect;
  e.link.onkeydown=function(ev){if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();openConnect(ev);}};
}

function showUser(d){
  var e=els();if(!e)return;remember(e);
  lastConnected=true;
  e.link.innerHTML=original.html;
  if(original.href)e.link.setAttribute('href',original.href);else e.link.removeAttribute('href');
  if(original.title)e.link.setAttribute('title',original.title);else e.link.removeAttribute('title');
  if(original.aria)e.link.setAttribute('aria-label',original.aria);else e.link.removeAttribute('aria-label');
  e.link.removeAttribute('role');e.link.removeAttribute('tabindex');e.link.onclick=null;e.link.onkeydown=null;
  var img=document.getElementById('pt-nb-avatar'),ph=document.getElementById('pt-nb-avatar-ph');
  if(d&&d.avatar&&img){img.src=d.avatar;img.style.display='block';if(ph)ph.style.display='none';}
  else if(ph){
    var n=(d&&(d.username||d.name||d.wallet||d.wallet_address))||'';
    ph.textContent=n?String(n).trim().slice(0,2).toUpperCase():'ME';ph.style.display='flex';
    if(img)img.style.display='none';
  }
}

function checkSession(force){
  var now=Date.now();
  if(checkInFlight)return;
  if(!force && now-lastCheckAt<MIN_CHECK_GAP_MS)return;
  lastCheckAt=now;checkInFlight=true;
  fetch('/api/me',{credentials:'include',cache:'no-store'}).then(function(r){
    if(r.status===429){return null;}
    if(!r.ok)throw new Error('not signed in');
    return r.json();
  }).then(function(d){
    if(d===null)return; // preserve current UI on rate-limit; do not retry-loop
    if(d&&d.ok){showUser(d);return;}
    showGuest();
  }).catch(function(){showGuest();}).finally(function(){checkInFlight=false;});
}

function boot(){
  revealHome();
  var e=els();if(!e)return;remember(e);
  showGuest();
  checkSession(true);
  try{
    if(sessionStorage.getItem('orca-open-connect')==='1'){
      sessionStorage.removeItem('orca-open-connect');
      setTimeout(function(){revealHome();startWalletConnect();},100);
    }
  }catch(_){}
}

if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
window.addEventListener('load',revealHome,{once:true});
window.addEventListener('pageshow',function(){revealHome();checkSession(false);});
document.addEventListener('visibilitychange',function(){if(!document.hidden){revealHome();checkSession(false);}});
})();
