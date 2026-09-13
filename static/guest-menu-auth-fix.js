/* Guest menu auth-state guard.
 * Keeps the mobile More menu consistent with the visible Connect button.
 * This intentionally does not depend on a specific disconnect-button class,
 * because the menu markup may be rebuilt by the mobile navbar.
 */
(function(){
'use strict';
if(!window.matchMedia('(max-width:767px)').matches)return;

function manualGuest(){
  try{return localStorage.getItem('orca_manual_disconnect')==='1';}catch(_){return false;}
}
function connectVisible(){
  var b=document.getElementById('oa-guest-connect-btn')||document.getElementById('oa-mobile-connect-wallet');
  if(!b)return false;
  var s=getComputedStyle(b);
  return s.display!=='none'&&s.visibility!=='hidden';
}
function guestNow(){return manualGuest()||connectVisible();}
function matchesText(el,re){return re.test(String(el.textContent||'').replace(/\s+/g,' ').trim());}
function apply(){
  var guest=guestNow();
  document.querySelectorAll('button,a,[role="button"]').forEach(function(el){
    if(matchesText(el,/^Disconnect Wallet$/i)){
      el.style.setProperty('display',guest?'none':'','important');
      el.setAttribute('aria-hidden',guest?'true':'false');
      el.dataset.oaConnectedOnly='1';
    }
    if(matchesText(el,/^Admin Console$/i)){
      if(guest){el.style.setProperty('display','none','important');el.setAttribute('aria-hidden','true');}
      el.dataset.oaConnectedOnly='1';
    }
  });
}
function schedule(){requestAnimationFrame(apply);setTimeout(apply,50);setTimeout(apply,250);}

if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',schedule,{once:true});else schedule();
window.addEventListener('pageshow',schedule);
window.addEventListener('orca:manual-disconnect',schedule);
window.addEventListener('orca:phantom-trusted-connected',schedule);
document.addEventListener('visibilitychange',function(){if(!document.hidden)schedule();});
document.addEventListener('click',function(e){
  var t=e.target&&e.target.closest?e.target.closest('button,a,[role="button"]'):null;
  if(t&&matchesText(t,/^Disconnect Wallet$/i))setTimeout(schedule,0);
},true);
try{new MutationObserver(schedule).observe(document.documentElement,{childList:true,subtree:true});}catch(_){}
})();
