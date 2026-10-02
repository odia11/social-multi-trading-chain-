// OrcAgent push notification subscription flow.
// Call _enablePushNotifications() from a button click (must be a real user
// gesture — browsers block permission prompts triggered automatically).
//
// Once permission is granted, every app load re-registers this device with
// the server (_syncPushSubscription). The server can lose a device (an old
// subscription it had to delete, a database restore, switching wallets on
// the same phone) while the phone still believes it is subscribed; before,
// nothing ever told the server again, so DMs and alerts silently stopped.
function _urlBase64ToUint8Array(base64String) {
  var padding = '='.repeat((4 - base64String.length % 4) % 4);
  var base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  var rawData = window.atob(base64);
  var outputArray = new Uint8Array(rawData.length);
  for (var i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}
async function _pushCsrfHeaders() {
  var meta = document.querySelector('meta[name="csrf-token"]');
  var token = (meta && meta.content) || window._csrfToken || '';
  if (!token) {
    try {
      var r = await fetch('/api/csrf-token', {credentials:'include', cache:'no-store'});
      var data = await r.json();
      token = (data && data.token) || '';
    } catch (_) {}
  }
  return {'Content-Type':'application/json','X-CSRF-Token':token,'X-CSRFToken':token};
}
// 'ok' | 'ios-browser' (iPhone/iPad Safari: push only works once OrcAgent is
// added to the Home Screen and opened from there) | 'unsupported'.
function _pushIsStandalone() {
  return window.navigator.standalone === true ||
    !!(window.matchMedia && window.matchMedia('(display-mode: standalone)').matches);
}
function _pushEnvironment() {
  var ua = navigator.userAgent || '';
  var ios = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  var standalone = _pushIsStandalone();
  var supported = ('serviceWorker' in navigator) && ('PushManager' in window) && ('Notification' in window);
  if (supported) return 'ok';
  if (ios && !standalone) return 'ios-browser';
  return 'unsupported';
}
var _PUSH_IOS_HINT = 'On iPhone, notifications only work from the OrcAgent app on your Home Screen: tap Share → Add to Home Screen, open OrcAgent from there and turn notifications on.';
async function _pushRegisterWithServer(sub) {
  var payload = sub.toJSON();
  try {
    var previous = localStorage.getItem('oa_push_endpoint') || '';
    if (previous && previous !== sub.endpoint) payload.previous_endpoint = previous;
  } catch (_) {}
  var res = await fetch('/api/push/subscribe', {
    method: 'POST',
    credentials: 'include',
    headers: await _pushCsrfHeaders(),
    body: JSON.stringify(payload)
  }).then(function(r) { return r.json(); });
  if (res && res.ok) {
    try { sessionStorage.setItem('oa_push_synced', sub.endpoint); } catch (_) {}
    try { localStorage.setItem('oa_push_endpoint', sub.endpoint); } catch (_) {}
  }
  return res;
}
async function _pushSubscription(reg) {
  var sub = await reg.pushManager.getSubscription();
  if (sub) return sub;
  var keyRes = await fetch('/api/push/vapid-public-key').then(function(r) { return r.json(); });
  if (!keyRes || !keyRes.key) throw new Error('Phone notifications are not set up on the server yet');
  return reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: _urlBase64ToUint8Array(keyRes.key)
  });
}
async function _enablePushNotifications() {
  var env = _pushEnvironment();
  if (env !== 'ok') {
    var msg = env === 'ios-browser' ? _PUSH_IOS_HINT : 'Push notifications are not supported on this browser.';
    if (typeof openAlertModal === 'function') openAlertModal({text: msg});
    return { ok: false, msg: msg };
  }
  try {
    var perm = await Notification.requestPermission();
    if (perm !== 'granted') {
      return { ok: false, msg: perm === 'denied'
        ? 'Notifications are blocked for OrcAgent — allow them in your browser or phone settings'
        : 'Permission not given' };
    }
    var reg = await navigator.serviceWorker.register('/sw.js');
    await navigator.serviceWorker.ready;
    var sub = await _pushSubscription(reg);
    return await _pushRegisterWithServer(sub);
  } catch (e) {
    console.error('[push] subscribe failed', e);
    return { ok: false, msg: String((e && e.message) || e) };
  }
}
async function _disablePushNotifications() {
  try {
    var reg = await navigator.serviceWorker.getRegistration();
    if (!reg) return { ok: true };
    var sub = await reg.pushManager.getSubscription();
    if (sub) {
        await fetch('/api/push/unsubscribe', {
        method: 'POST',
        credentials: 'include',
        headers: await _pushCsrfHeaders(),
        body: JSON.stringify({ endpoint: sub.endpoint })
      }).catch(function() {});
      await sub.unsubscribe();
    }
    try { sessionStorage.removeItem('oa_push_synced'); } catch (_) {}
    try { localStorage.removeItem('oa_push_endpoint'); } catch (_) {}
    return { ok: true };
  } catch (e) {
    return { ok: false, msg: String(e) };
  }
}
async function _isPushSubscribed() {
  if (!('serviceWorker' in navigator)) return false;
  try {
    var reg = await navigator.serviceWorker.getRegistration();
    if (!reg) return false;
    var sub = await reg.pushManager.getSubscription();
    return !!sub;
  } catch (e) {
    return false;
  }
}
// Re-register this device with the server on every app load once the user
// has allowed notifications (no prompt: permission is already granted).
async function _syncPushSubscription() {
  if (_pushEnvironment() !== 'ok' || Notification.permission !== 'granted') return;
  try {
    // Settings opt-out wins even though the browser-level permission remains
    // granted. Without this guard, the next app load would silently subscribe
    // the device again immediately after the user switched notifications off.
    if (localStorage.getItem('oa_push_opt_out') === '1') return;
    var reg = await navigator.serviceWorker.getRegistration('/sw.js') ||
              await navigator.serviceWorker.register('/sw.js');
    await navigator.serviceWorker.ready;
    var sub = await _pushSubscription(reg);
    var synced = '';
    try { synced = sessionStorage.getItem('oa_push_synced') || ''; } catch (_) {}
    if (synced === sub.endpoint) return;
    await _pushRegisterWithServer(sub);
  } catch (_) {}
}
async function _sendTestPush() {
  await _syncPushSubscription();
  var r = await fetch('/api/push/test', {
    method: 'POST', credentials: 'include', headers: await _pushCsrfHeaders(), body: '{}'
  }).then(function(x) { return x.json(); }).catch(function() { return null; });
  var msg = r && r.ok
    ? 'Test notification sent — it should appear on your phone within a few seconds. Nothing? Check that notifications for OrcAgent are allowed in your phone settings.'
    : ((r && r.msg) || 'Could not send a test notification');
  if (typeof openAlertModal === 'function') openAlertModal({text: msg}); else alert(msg);
  return r;
}

// A slim "turn on notifications" card on pages that hold one
// (<div id="oa-push-prompt"></div>): Messages and Notifications. Shown until
// the user has turned them on, and for a week after it is dismissed.
function _mountPushPrompt() {
  var host = document.getElementById('oa-push-prompt');
  if (!host) return;
  try {
    var until = Number(localStorage.getItem('oa_push_prompt_dismissed') || 0);
    if (until > Date.now()) return;
  } catch (_) {}
  var env = _pushEnvironment(), perm = ('Notification' in window) ? Notification.permission : 'default';
  var text = '', button = '';
  // Installed OrcAgent PWAs use default-on push: the first normal tap opens
  // the one OS/browser permission prompt. No extra in-app "Turn on" step.
  if (_pushIsStandalone() && perm === 'default') return;
  if (env === 'ios-browser') text = _PUSH_IOS_HINT;
  else if (env !== 'ok' || perm === 'granted') return;
  else if (perm === 'denied') text = 'Notifications are blocked for OrcAgent. Allow them in your browser or phone settings to get DMs and replies.';
  else { text = 'Get a notification on your phone when someone sends you a DM, replies or follows you.'; button = 'Turn on'; }
  if (!document.getElementById('oa-push-prompt-css')) {
    var st = document.createElement('style');
    st.id = 'oa-push-prompt-css';
    st.textContent = '.oa-push-prompt{display:flex;align-items:center;gap:10px;margin:10px 12px;padding:11px 12px;border:1px solid rgba(247,185,85,.28);border-radius:12px;background:rgba(247,185,85,.07);color:#e8edf2;font-size:12.5px;line-height:1.4}.oa-push-prompt span{flex:1;min-width:0;overflow-wrap:anywhere}.oa-push-prompt button{flex:0 0 auto;border:0;border-radius:9px;padding:8px 12px;font-weight:700;font-size:12px;font-family:inherit;cursor:pointer}.oa-push-prompt .oa-pp-on{background:#f7b955;color:#111}.oa-push-prompt .oa-pp-x{background:transparent;color:#8a919c;padding:6px 8px;font-size:16px;line-height:1}';
    document.head.appendChild(st);
  }
  host.innerHTML = '';
  var card = document.createElement('div');
  card.className = 'oa-push-prompt';
  card.setAttribute('role', 'status');
  var span = document.createElement('span');
  span.textContent = text;
  card.appendChild(span);
  if (button) {
    var on = document.createElement('button');
    on.type = 'button'; on.className = 'oa-pp-on'; on.textContent = button;
    on.addEventListener('click', async function() {
      on.disabled = true;
      var r = await _enablePushNotifications();
      if (r && r.ok) { span.textContent = 'Notifications are on for this device.'; on.remove(); setTimeout(function() { host.innerHTML = ''; }, 2500); }
      else { on.disabled = false; span.textContent = (r && r.msg) || 'Could not turn notifications on.'; }
    });
    card.appendChild(on);
  }
  var x = document.createElement('button');
  x.type = 'button'; x.className = 'oa-pp-x'; x.setAttribute('aria-label', 'Dismiss'); x.textContent = '×';
  x.addEventListener('click', function() {
    try { localStorage.setItem('oa_push_prompt_dismissed', String(Date.now() + 7 * 86400000)); } catch (_) {}
    host.innerHTML = '';
  });
  card.appendChild(x);
  host.appendChild(card);
}
function _armPwaDefaultPush() {
  if (_pushEnvironment() !== 'ok' || !_pushIsStandalone() || Notification.permission !== 'default') return;
  try { if (localStorage.getItem('oa_push_opt_out') === '1') return; } catch (_) {}
  var fired = false;
  var start = function(ev) {
    if (fired || (ev && ev.isTrusted === false)) return;
    fired = true;
    ['pointerup','touchend','click'].forEach(function(t){ document.removeEventListener(t,start,true); });
    _enablePushNotifications().catch(function(){});
  };
  ['pointerup','touchend','click'].forEach(function(t){ document.addEventListener(t,start,{capture:true,passive:true}); });
}
(function() {
  function boot() { _syncPushSubscription(); _armPwaDefaultPush(); _mountPushPrompt(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
