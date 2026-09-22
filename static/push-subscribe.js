// OrcAgent push notification subscription flow.
// Call _enablePushNotifications() from a button click (must be a real user
// gesture — browsers block permission prompts triggered automatically).
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
async function _enablePushNotifications() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    openAlertModal({text:'Push notifications are not supported on this browser.'});
    return { ok: false, msg: 'Not supported' };
  }
  try {
    var perm = await Notification.requestPermission();
    if (perm !== 'granted') {
      return { ok: false, msg: 'Permission denied' };
    }
    var reg = await navigator.serviceWorker.register('/sw.js');
    await navigator.serviceWorker.ready;
    var keyRes = await fetch('/api/push/vapid-public-key').then(function(r) { return r.json(); });
    var appServerKey = _urlBase64ToUint8Array(keyRes.key);
    var sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: appServerKey
      });
    }
    var subJson = sub.toJSON();
    var res = await fetch('/api/push/subscribe', {
      method: 'POST',
      credentials: 'include',
      headers: await _pushCsrfHeaders(),
      body: JSON.stringify(subJson)
    }).then(function(r) { return r.json(); });
    return res;
  } catch (e) {
    console.error('[push] subscribe failed', e);
    return { ok: false, msg: String(e) };
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
