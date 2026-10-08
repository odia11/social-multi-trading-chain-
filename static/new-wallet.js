(function () {
'use strict';
const alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
let pending = null, dialog = null, previousFocus = null, revision = 0, busy = false;
function encode(bytes) {
  let n = 0n, out = '', zeros = 0;
  for (const byte of bytes) n = n * 256n + BigInt(byte);
  while (n) { out = alphabet[Number(n % 58n)] + out; n /= 58n; }
  while (zeros < bytes.length && bytes[zeros] === 0) zeros++;
  return '1'.repeat(zeros) + out;
}
function decode(value) {
  if (!value || value.length > 100) throw new Error('Invalid base58 private key.');
  let n = 0n, zeros = 0, bytes = [];
  for (const c of value) {
    const index = alphabet.indexOf(c);
    if (index < 0) throw new Error('Invalid base58 private key.');
    n = n * 58n + BigInt(index);
  }
  while (n) { bytes.unshift(Number(n % 256n)); n /= 256n; }
  while (zeros < value.length && value[zeros] === '1') zeros++;
  return new Uint8Array([...new Array(zeros).fill(0), ...bytes]);
}
async function post(url, body) {
  const csrf = await fetch('/api/csrf-token', {credentials:'same-origin', cache:'no-store'}).then(r => r.json());
  const r = await fetch(url, {method:'POST', credentials:'same-origin', cache:'no-store',
    headers:{'Content-Type':'application/json', 'X-CSRF-Token':csrf.token || ''}, body:JSON.stringify(body)});
  const data = await r.json();
  if (!r.ok || !data.ok) throw new Error(data.error?.message || data.error || data.msg || 'Request failed.');
  return data;
}
function wipe() {
  revision++;
  if (pending) { pending.private_key = ''; pending.token = ''; pending = null; }
  if (dialog) dialog.querySelectorAll('input, textarea').forEach(e => { e.value = ''; });
}
function close() {
  if (busy) return;
  wipe();
  if (dialog?.open) dialog.close();
  previousFocus?.focus();
}
function shell(content) {
  if (!dialog) {
    dialog = document.createElement('dialog'); dialog.id = 'oa-new-wallet';
    dialog.setAttribute('aria-labelledby', 'nw-title');
    document.body.appendChild(dialog);
    dialog.addEventListener('cancel', e => { e.preventDefault(); close(); });
    dialog.addEventListener('click', e => { if (e.target === dialog) close(); });
  }
  dialog.innerHTML = '<button type="button" class="nw-close" aria-label="Close wallet setup">×</button>' + content;
  dialog.querySelector('.nw-close').onclick = close;
  if (!dialog.open) { previousFocus = document.activeElement; dialog.showModal(); }
  const back = dialog.querySelector('[data-back]');
  if (back) back.onclick = () => { if (!busy) open(); };
  dialog.querySelector('input, button:not(.nw-close)')?.focus();
}
function message(text) { dialog.querySelector('[role="status"]').textContent = text; }
function lock(value) {
  busy = value;
  dialog.querySelectorAll('button').forEach(button => { button.disabled = value; });
}
function finish() {
  busy = false; wipe(); dialog.close();
  try { localStorage.removeItem('orca_manual_disconnect'); } catch (_) {}
  // Reload the current route so every guest widget picks up the full session.
  location.reload();
}
function icon(name) {
  const paths = {
    wallet: '<path d="M20 8V5a2 2 0 0 0-2-2H5a3 3 0 0 0 0 6h15v11H5a3 3 0 0 1-3-3V6"/><path d="M20 12h-5v4h5M8 13v6m-3-3h6"/>',
    phantom: '<path d="M4 18V11a8 8 0 0 1 16 0v8l-4-2-4 2-4-2-4 2Z"/><path d="M9 10v2m6-2v2"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    key: '<circle cx="8" cy="8" r="5"/><path d="m12 12 9 9m-3-3 3-3m-6 0 3-3"/>',
    shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
    arrow: '<path d="m9 5 7 7-7 7"/>'
  };
  return '<svg data-nw-icon="' + name + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths[name] + '</svg>';
}
function choice(action, symbol, title, subtitle, featured) {
  return '<button type="button" aria-label="' + title + '" class="nw-option' + (featured ? ' nw-featured' : '') + '" data-' + action + '>' +
    '<span class="nw-icon nw-icon-' + symbol + '">' + icon(symbol) + '</span><span class="nw-copy">' +
    '<span class="nw-option-title">' + title + '</span>' +
    (featured ? '<span class="nw-recommended">RECOMMENDED</span>' : '') +
    '<span class="nw-option-sub">' + subtitle + '</span></span><span class="nw-arrow">' + icon('arrow') + '</span></button>';
}
function open() {
  wipe();
  shell('<div class="nw-handle" aria-hidden="true"></div><div class="nw-brand">ORCAGENT</div>' +
    '<h2 id="nw-title">Set up your wallet</h2><p class="nw-subtitle">Choose how you want to continue.</p>' +
    '<div class="nw-choices">' +
    choice('create', 'wallet', 'Create new wallet', 'No wallet app needed. Start trading.', true) +
    choice('phantom', 'phantom', 'Connect Phantom', 'Use your existing Phantom wallet.') +
    choice('address', 'eye', 'Enter address', 'View only · trading is disabled.') +
    choice('import', 'key', 'Import key / sign in', 'Sign in with your saved private key.') + '</div>' +
    '<div class="nw-security">' + icon('shield') + '<p>Trading keys are stored encrypted.<br>Back up your key before continuing.</p></div>');
  dialog.querySelector('[data-create]').onclick = create;
  dialog.querySelector('[data-import]').onclick = importView;
  dialog.querySelector('[data-address]').onclick = addressView;
  dialog.querySelector('[data-phantom]').onclick = () => {
    close();
    if (typeof window.connectWalletOnboard === 'function') window.connectWalletOnboard('phantom', location.pathname + location.search + location.hash);
    else location.href = '/?wallet_connect=phantom&return_to=' + encodeURIComponent(location.pathname + location.search + location.hash);
  };
}
async function create() {
  wipe(); const attempt = revision;
  shell('<h2 id="nw-title">Creating your wallet</h2><p>Preparing your backup…</p><div role="status"></div>');
  try {
    const data = await post('/api/account/create-wallet/start', {});
    if (attempt !== revision || !dialog.open) return;
    pending = data;
    shell('<button data-back type="button">← Back</button><h2 id="nw-title">Back up your wallet</h2>' +
      '<p>Save this private key securely. It is shown only during this setup and cannot be retrieved later. Setup expires after 10 minutes. Do not fund this wallet until activation succeeds.</p>' +
      '<label>Solana address<input id="nw-address" readonly></label><label>Private key<input id="nw-key" type="password" readonly autocomplete="off"></label>' +
      '<div class="nw-row"><button type="button" data-show>Show key</button><button type="button" data-copy>Copy key</button></div>' +
      '<form id="nw-confirm"><label>Username<input name="username" required maxlength="20" pattern="[A-Za-z0-9_]+" autocomplete="username"></label>' +
      '<label>Password<input name="password" type="password" required minlength="10" autocomplete="new-password"></label>' +
      '<label class="nw-backup"><input name="backup" type="checkbox" required> I saved my private key securely.</label>' +
      '<button type="submit" disabled data-activate>Activate account</button></form><div role="status" aria-live="polite"></div>');
    dialog.querySelector('#nw-address').value = data.address;
    dialog.querySelector('#nw-key').value = data.private_key;
    dialog.querySelector('[data-show]').onclick = e => {
      const input = dialog.querySelector('#nw-key'); input.type = input.type === 'password' ? 'text' : 'password';
      e.target.textContent = input.type === 'password' ? 'Show key' : 'Hide key';
    };
    dialog.querySelector('[data-copy]').onclick = async () => {
      try { await navigator.clipboard.writeText(pending.private_key); message('Key copied. Store it somewhere safe.'); }
      catch (_) { message('Use Show key and copy it manually.'); }
    };
    const form = dialog.querySelector('#nw-confirm');
    form.addEventListener('input', () => { form.querySelector('[data-activate]').disabled = !form.checkValidity(); });
    form.onsubmit = async e => {
      e.preventDefault(); if (busy || !form.reportValidity()) return;
      const values = new FormData(form); lock(true);
      try {
        await post('/api/account/create-wallet/confirm', {token:pending.token, confirmed_backup:values.get('backup') === 'on',
          username:values.get('username'), password:values.get('password')});
        finish();
      } catch (err) {
        // A request may have consumed the token even if its response was lost.
        wipe(); lock(false);
        shell('<h2 id="nw-title">Account setup interrupted</h2><p role="status"></p><button data-back type="button">Return to wallet setup</button>');
        message(err.message + ' If activation completed, sign in using your saved key or password. Otherwise create a new wallet.');
      }
    };
  } catch (err) {
    if (attempt !== revision || !dialog.open) return;
    shell('<h2 id="nw-title">Could not create wallet</h2><p role="status"></p><button data-back type="button">Back</button>'); message(err.message);
  }
}
function importView() {
  wipe();
  shell('<button data-back type="button">← Back</button><h2 id="nw-title">Sign in with your key</h2>' +
    '<p>Your key stays in this browser. Only a signature is sent to OrcAgent. Importing does not enable server trading for a wallet without a stored trading key.</p>' +
    '<form><label>Base58 Solana private key<input name="key" type="password" autocomplete="off" required spellcheck="false" autocapitalize="none"></label>' +
    '<button type="submit">Sign in</button></form><div role="status" aria-live="polite"></div>');
  const form = dialog.querySelector('form');
  form.onsubmit = async e => {
    e.preventDefault(); if (busy) return; lock(true);
    let raw, keypair, derived;
    try {
      if (!window.nacl?.sign) throw new Error('Wallet library unavailable. Reload and try again.');
      const field = form.elements.key;
      raw = decode(field.value.trim()); field.value = '';
      if (raw.length !== 64) throw new Error('Use the full 64-byte Solana private key in base58.');
      derived = nacl.sign.keyPair.fromSeed(raw.subarray(0, 32));
      if (!derived.publicKey.every((byte, i) => byte === raw[i + 32])) throw new Error('Invalid private key.');
      keypair = derived;
      const address = encode(keypair.publicKey);
      const nonceResponse = await fetch('/api/auth/nonce', {credentials:'same-origin', cache:'no-store'});
      const data = await nonceResponse.json();
      if (!nonceResponse.ok || !data.nonce) throw new Error('Could not obtain login nonce.');
      const signature = encode(nacl.sign.detached(new TextEncoder().encode('OrcAgent verification\n\nCode: ' + data.nonce), keypair.secretKey));
      raw.fill(0); keypair.secretKey.fill(0);
      await post('/api/wallet/set', {address, nonce:data.nonce, signature});
      finish();
    } catch (err) { message(err.message); lock(false); }
    finally { raw?.fill(0); derived?.secretKey.fill(0); }
  };
}
function addressView() {
  wipe();
  shell('<button data-back type="button">← Back</button><h2 id="nw-title">Enter address</h2><p>View only. Trading requires a full account.</p>' +
    '<form><label>Solana address<input name="address" required autocomplete="off" spellcheck="false" autocapitalize="none"></label>' +
    '<button type="submit">Continue in view-only mode</button></form><div role="status" aria-live="polite"></div>');
  const form = dialog.querySelector('form');
  form.onsubmit = async e => {
    e.preventDefault(); if (busy) return; lock(true);
    try { await post('/api/wallet/connect-readonly', {address:form.elements.address.value.trim()}); finish(); }
    catch (err) { message(err.message); lock(false); }
  };
}
document.addEventListener('click', e => {
  const target = e.target.closest?.('#oa-guest-connect-btn,.pt-nb-profile-link[data-oa-auth="guest"],#guest-banner .gb-link,.gb-link,[data-new-wallet]');
  if (!target) return;
  e.preventDefault(); e.stopImmediatePropagation(); open();
}, true);
window.addEventListener('pagehide', wipe);
// Retain the existing entry point used by dashboard and standalone pages.
window.OrcAgentWalletOnboarding = {open};
window.OrcAgentNewWallet = {open, create};
})();
