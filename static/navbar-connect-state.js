/* OrcAgent shared navbar auth-state control.
   Logged out: show a clear Connect Wallet control in the top-right slot.
   Logged in: restore the normal user profile avatar/link.
   Home always stays browsable; the old full-screen onboarding gate is never shown. */
(function(){
'use strict';

var original=null;
var authState='guest';
var lastUser=null;
var checkInFlight=false;
var lastCheckAt=0;
var reconcileQueued=false;
var MIN_CHECK_GAP_MS=15000;

function manualDisconnectRequested(){
  try{return localStorage.getItem('orca_manual_disconnect')==='1';}catch(_){return false;}
}

function els(){
  var link=document.querySelector('.pt-nb-profile-link');
  if(!link)return null;
  return {link:link,img:document.getElementById('pt-nb-avatar'),ph:document.getElementById('pt-nb-avatar-ph')};
}

function remember(e){
  if(original||!e)return;
  original={html:e.link.innerHTML,href:e.link.getAttribute('href')||'',title:e.link.getAttribute('title')||'',aria:e.link.getAttribute('aria-label')||''};
}

function connectMarkup(){
  return '<span class="pt-nb-connect-pill" aria-hidden="true" style="display:flex;align-items:center;justify-content:center;gap:6px;height:38px;padding:0 11px;border-radius:12px;background:rgba(247,185,85,.12);border:1px solid rgba(247,185,85,.58);color:#f7b955;font-weight:700;font-size:12px;line-height:1;white-space:nowrap">'
    +'<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    +'<path d="M4 7h13a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h12"/>'
    +'<path d="M16 12h5v4h-5a2 2 0 0 1 0-4z"/><circle cx="17.5" cy="14" r=".5" fill="currentColor" stroke="none"/>'
    +'</svg><span>Connect</span></span>';
}

function revealHome(){
  var ob=document.getElementById('onboard');
  var app=document.getElementById('app');
  if(ob){ob.classList.add('hide');ob.style.display='none';ob.setAttribute('aria-hidden','true');}
  if(app)app.style.display='flex';
}

function startWalletConnect(){
  try{localStorage.removeItem('orca_manual_disconnect');}catch(_){}
  var phantomBtn=document.getElementById('phantom-ob-btn');
  if(phantomBtn){try{phantomBtn.click();return true;}catch(_){}}
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
  else setTimeout(startWalletConnect,150);
  return false;
}

function wireGuestConnect(){
  document.querySelectorAll('#guest-banner .gb-link,.gb-link').forEach(function(btn){
    btn.onclick=openConnect;
    btn.setAttribute('aria-label','Connect Wallet');
  });
}

function renderGuest(){
  authState='guest';lastUser=null;
  var e=els();
  if(e){
    remember(e);
    if(e.link.getAttribute('data-oa-auth')!=='guest'){
      e.link.removeAttribute('href');
      e.link.setAttribute('data-oa-auth','guest');
      e.link.setAttribute('role','button');
      e.link.setAttribute('tabindex','0');
      e.link.setAttribute('title','Connect Wallet');
      e.link.setAttribute('aria-label','Connect Wallet');
      e.link.style.width='auto';
      e.link.style.minWidth='0';
      e.link.style.borderRadius='12px';
      e.link.innerHTML=connectMarkup();
      e.link.onclick=openConnect;
      e.link.onkeydown=function(ev){if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();openConnect(ev);}};
    }
  }
  wireGuestConnect();
}

function renderUser(d){
  if(manualDisconnectRequested()){renderGuest();return;}
  authState='user';lastUser=d||lastUser;
  var e=els();if(!e)return;remember(e);
  if(e.link.getAttribute('data-oa-auth')!=='user'){
    e.link.setAttribute('data-oa-auth','user');
    e.link.style.width='';e.link.style.minWidth='';e.link.style.borderRadius='';
    e.link.innerHTML=original.html;
    if(original.href)e.link.setAttribute('href',original.href);else e.link.removeAttribute('href');
    if(original.title)e.link.setAttribute('title',original.title);else e.link.removeAttribute('title');
    if(original.aria)e.link.setAttribute('aria-label',original.aria);else e.link.removeAttribute('aria-label');
    e.link.removeAttribute('role');e.link.removeAttribute('tabindex');e.link.onclick=null;e.link.onkeydown=null;
  }
  var img=document.getElementById('pt-nb-avatar'),ph=document.getElementById('pt-nb-avatar-ph'),u=lastUser||{};
  if(u.avatar&&img){img.src=u.avatar;img.style.display='block';if(ph)ph.style.display='none';}
  else if(ph){
    var n=(u.username||u.name||u.wallet||u.wallet_address||'');
    ph.textContent=n?String(n).trim().slice(0,2).toUpperCase():'ME';ph.style.display='flex';
    if(img)img.style.display='none';
  }
}

function reconcileChrome(){
  reconcileQueued=false;
  revealHome();
  if(manualDisconnectRequested())authState='guest';
  var e=els();
  if(!e){wireGuestConnect();return;}
  if(authState==='user'){
    if(e.link.getAttribute('data-oa-auth')!=='user')renderUser(lastUser);
  }else if(e.link.getAttribute('data-oa-auth')!=='guest')renderGuest();
  else wireGuestConnect();
}

function queueReconcile(){
  if(reconcileQueued)return;
  reconcileQueued=true;
  requestAnimationFrame(reconcileChrome);
}

function checkSession(force){
  if(manualDisconnectRequested()){renderGuest();return;}
  var now=Date.now();
  if(checkInFlight)return;
  if(!force&&now-lastCheckAt<MIN_CHECK_GAP_MS)return;
  lastCheckAt=now;checkInFlight=true;
  fetch('/api/me',{credentials:'include',cache:'no-store'}).then(function(r){
    if(r.status===429)return null;
    if(!r.ok)throw new Error('not signed in');
    return r.json();
  }).then(function(d){
    if(manualDisconnectRequested()){renderGuest();return;}
    if(d===null)return;
    if(d&&d.ok){renderUser(d);return;}
    renderGuest();
  }).catch(function(){renderGuest();}).finally(function(){checkInFlight=false;});
}

function onManualDisconnect(){
  try{localStorage.setItem('orca_manual_disconnect','1');}catch(_){}
  window.__ORCA_TRUSTED_PHANTOM_PUBLIC_KEY='';
  renderGuest();
  queueReconcile();
}

function boot(){
  revealHome();
  if(manualDisconnectRequested())renderGuest();
  else {renderGuest();checkSession(true);}
  try{
    if(sessionStorage.getItem('orca-open-connect')==='1'){
      sessionStorage.removeItem('orca-open-connect');
      setTimeout(function(){revealHome();startWalletConnect();},100);
    }
  }catch(_){}
  new MutationObserver(queueReconcile).observe(document.documentElement,{childList:true,subtree:true});
  setTimeout(queueReconcile,250);
  setTimeout(queueReconcile,1000);
}

if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
window.addEventListener('load',queueReconcile,{once:true});
window.addEventListener('orca:manual-disconnect',onManualDisconnect);
window.addEventListener('pageshow',function(){queueReconcile();checkSession(false);});
document.addEventListener('visibilitychange',function(){if(!document.hidden){queueReconcile();checkSession(false);}});
document.addEventListener('click',function(e){
  var t=e.target&&e.target.closest?e.target.closest('button,a,[role="button"]'):null;
  if(t&&/disconnect wallet/i.test((t.textContent||'').trim())){
    onManualDisconnect();
    try{window.dispatchEvent(new CustomEvent('orca:manual-disconnect'));}catch(_){}
  }
},true);
})();
