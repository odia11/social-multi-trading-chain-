/* OrcAgent silent Phantom reconnect.
 *
 * Rehydrates Phantom's provider connection after refresh/revisit without ever
 * showing a wallet popup. OrcAgent's server session remains authoritative and
 * is restored separately by the existing cookie/device-token recovery flow.
 */
(function(){
'use strict';

var _orcaTrustedConnectInFlight = null;
var _orcaLastTrustedAttempt = 0;

function _manualDisconnectRequested(){
  try { return !!localStorage.getItem('orca_manual_disconnect'); }
  catch (_) { return false; }
}

function _phantomProvider(){
  if (window.phantom && window.phantom.solana && window.phantom.solana.isPhantom) {
    return window.phantom.solana;
  }
  if (window.solana && window.solana.isPhantom) return window.solana;
  return null;
}

function _publishTrustedWallet(provider, response){
  var key = null;
  try {
    key = (response && response.publicKey) || provider.publicKey || null;
    key = key && typeof key.toString === 'function' ? key.toString() : (key ? String(key) : '');
  } catch (_) { key = ''; }
  if (!key) return '';

  window.__ORCA_TRUSTED_PHANTOM_PUBLIC_KEY = key;
  try {
    window.dispatchEvent(new CustomEvent('orca:phantom-trusted-connected', {
      detail: { publicKey: key }
    }));
  } catch (_) {}
  return key;
}

async function _trustedReconnect(){
  if (_manualDisconnectRequested()) return '';

  var provider = _phantomProvider();
  if (!provider || typeof provider.connect !== 'function') return '';

  if (provider.isConnected && provider.publicKey) {
    return _publishTrustedWallet(provider, null);
  }

  if (_orcaTrustedConnectInFlight) return _orcaTrustedConnectInFlight;

  // Avoid hammering Phantom when Safari fires pageshow + visibilitychange in
  // quick succession while resuming from the background.
  var now = Date.now();
  if (now - _orcaLastTrustedAttempt < 1500) return '';
  _orcaLastTrustedAttempt = now;

  _orcaTrustedConnectInFlight = Promise.resolve()
    .then(function(){
      // onlyIfTrusted:true is the important part: Phantom reconnects only when
      // this origin was trusted before and MUST NOT display an approval popup.
      return provider.connect({ onlyIfTrusted: true });
    })
    .then(function(response){
      return _publishTrustedWallet(provider, response);
    })
    .catch(function(){
      // Untrusted/not-installed/temporarily unavailable is not a logout. The
      // server recovery flow may still restore the OrcAgent session.
      return '';
    })
    .finally(function(){ _orcaTrustedConnectInFlight = null; });

  return _orcaTrustedConnectInFlight;
}

function _tryWithLateInjection(attempt){
  attempt = attempt || 0;
  _trustedReconnect().then(function(key){
    if (!key && !_phantomProvider() && attempt < 10) {
      setTimeout(function(){ _tryWithLateInjection(attempt + 1); }, 200);
    }
  });
}

function _onVisible(){
  if (document.visibilityState && document.visibilityState !== 'visible') return;
  _tryWithLateInjection(0);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', function(){ _tryWithLateInjection(0); }, { once:true });
} else {
  _tryWithLateInjection(0);
}
window.addEventListener('load', function(){ _tryWithLateInjection(0); }, { once:true });
window.addEventListener('pageshow', function(){ _onVisible(); });
document.addEventListener('visibilitychange', _onVisible, { passive:true });
window.addEventListener('online', _onVisible, { passive:true });

window.orcaTrustedPhantomReconnect = _trustedReconnect;
})();
