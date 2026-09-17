/* Cross-chain buys, from the Buy button to the finished trade.
 *
 * WHY THIS IS A SEPARATE FILE
 * A same-chain buy is one request: you press Buy, it answers, you are done.
 * A cross-chain buy is not. The request comes back in seconds with the bridge
 * still in flight, and the trade finishes minutes later in a background worker
 * that has nothing to do with this page. So the page cannot own the outcome --
 * it can only follow it, and it has to be able to pick that up again after a
 * refresh, on another tab, or tomorrow.
 *
 * THE RULE THAT SHAPES ALL OF IT
 * The trade id is the trade. It is written to localStorage before the poll
 * starts and read back on load, so a refresh RECONNECTS instead of starting a
 * second trade. There is no path here that executes without a quote id, and
 * no path that executes twice for one quote.
 */
(function () {
  'use strict';

  var STORE_KEY = 'orca_cc_trade';
  var POLL_MS = 3000;
  var _pollTimer = null;
  var _watching = '';

  /* The seven things a user is told, in order. The backend sends its own
   * progress sentence; this is the stepper around it, and the two come from
   * the same state so they cannot disagree. */
  var STEPS = [
    { key: 'prepare', label: 'Preparing route',
      states: ['CREATED', 'QUOTED', 'ROUTE_SELECTED', 'RESERVED'] },
    { key: 'sign',    label: 'Waiting for signature', states: ['EXECUTING'] },
    { key: 'source',  label: 'Sending from source',   states: ['AWAITING_SOURCE'] },
    { key: 'bridge',  label: 'Bridging',              states: ['BRIDGING'] },
    { key: 'arrived', label: 'Funds arrived',         states: ['DEST_RECEIVED'] },
    { key: 'buy',     label: 'Buying token',          states: ['SWAPPING', 'CONFIRMING'] },
    { key: 'done',    label: 'Complete',              states: ['COMPLETED'] }
  ];

  /* States where nothing more will happen on its own. REFUNDED and
   * MANUAL_REVIEW are finished for the engine but are NOT successes, and the
   * UI must never round them into one. */
  var TERMINAL = ['COMPLETED', 'FAILED', 'CANCELLED', 'REFUNDED', 'MANUAL_REVIEW'];
  var BAD = ['FAILED', 'CANCELLED', 'MANUAL_REVIEW'];

  function stepIndex(state) {
    for (var i = 0; i < STEPS.length; i++) {
      if (STEPS[i].states.indexOf(state) !== -1) return i;
    }
    // An unknown state is not progress. Sitting at the start is honest;
    // guessing it is nearly done is not.
    return TERMINAL.indexOf(state) !== -1 ? STEPS.length - 1 : 0;
  }

  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function csrf() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return (m && m.content) || (window._lmCsrf || '');
  }

  function headers() {
    var c = csrf();
    var h = { 'Content-Type': 'application/json', 'X-CSRF-Token': c,
              'X-CSRFToken': c, 'X-Requested-With': 'XMLHttpRequest' };
    var s = window._lmClientSecret
         || (document.querySelector('meta[name="client-secret"]') || {}).content || '';
    if (s) h['X-API-Shared-Secret'] = s;
    return h;
  }

  /* ── remembering which trade this browser is following ── */
  function remember(tradeId, meta) {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({
        trade_id: tradeId, symbol: (meta && meta.symbol) || '',
        token_address: (meta && meta.token_address) || '',
        started_at: Date.now()
      }));
    } catch (e) { /* private window, or storage full. The poll still runs. */ }
  }

  function forget() {
    try { localStorage.removeItem(STORE_KEY); } catch (e) {}
  }

  function remembered() {
    try {
      var raw = localStorage.getItem(STORE_KEY);
      if (!raw) return null;
      var v = JSON.parse(raw);
      // A trade older than a day is not one this page should still be
      // following. The server still knows about it; this is only the banner.
      if (!v || !v.trade_id || (Date.now() - (v.started_at || 0)) > 86400000) {
        forget(); return null;
      }
      return v;
    } catch (e) { return null; }
  }

  /* ── the panel ── */
  function host() {
    var el = document.getElementById('orca-cc-progress');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'orca-cc-progress';
    el.className = 'cc-progress';
    document.body.appendChild(el);
    return el;
  }

  function render(d) {
    var el = host();
    var state = (d && d.state) || 'CREATED';
    var idx = stepIndex(state);
    var failed = BAD.indexOf(state) !== -1;
    var done = state === 'COMPLETED';
    var refunded = state === 'REFUNDED';

    var steps = STEPS.map(function (s, i) {
      var cls = i < idx ? 'done' : (i === idx ? (failed ? 'bad' : 'now') : 'todo');
      if (done) cls = 'done';
      var label = s.label;
      if (s.key === 'source' && d.source_chain) label = 'Sending from ' + chainName(d.source_chain);
      if (s.key === 'bridge' && d.destination_chain) label = 'Bridging to ' + chainName(d.destination_chain);
      return '<li class="cc-step ' + cls + '"><span class="cc-dot"></span>'
           + '<span class="cc-step-label">' + esc(label) + '</span></li>';
    }).join('');

    // Where the money is. "This trade did not complete" is the same sentence
    // whether nothing left the source chain or the bridge worked and only the
    // purchase did not -- and in the second case the user's dollars are on the
    // OTHER chain. The server says which; this is where they read it.
    var whereNote = d.funds_note
      ? '<div class="cc-note where">' + esc(d.funds_note) + '</div>' : '';

    var note = '';
    if (failed) {
      note = '<div class="cc-note bad">' + esc(d.failure_reason || 'This trade did not complete')
           + (state === 'MANUAL_REVIEW'
               ? ' <strong>Your funds are still reserved while this is checked.</strong>' : '')
           + '</div>' + whereNote;
    } else if (refunded) {
      note = '<div class="cc-note">The bridge did not go through and your USDC was returned.</div>';
    } else if (!done) {
      note = '<div class="cc-note">' + esc(d.progress || 'Working…')
           + ' You can close this page — the trade carries on without it.</div>';
    }

    var links = '';
    [['source_tx_hash', 'Source tx'], ['destination_tx_hash', 'Destination tx'],
     ['swap_tx_hash', 'Swap tx']].forEach(function (pair) {
      if (d[pair[0]]) {
        links += '<div class="cc-tx"><span>' + pair[1] + '</span><code>'
               + esc(String(d[pair[0]]).slice(0, 10)) + '…</code></div>';
      }
    });

    el.innerHTML =
        '<div class="cc-card">'
      +   '<div class="cc-head">'
      +     '<strong>' + (done ? 'Trade complete' : (failed ? 'Needs attention' : 'Trade in progress')) + '</strong>'
      +     '<button class="cc-close" onclick="OrcaCrossChain.dismiss()" aria-label="Hide">&times;</button>'
      +   '</div>'
      +   '<ol class="cc-steps">' + steps + '</ol>'
      +   note + links
      + '</div>';
    el.style.display = 'block';
  }

  function chainName(c) {
    var names = { solana: 'Solana', base: 'Base', bsc: 'BNB Chain',
                  arbitrum: 'Arbitrum', polygon: 'Polygon', robinhood: 'Robinhood' };
    return names[c] || c;
  }

  /* ── following one trade to the end ── */
  function poll(tradeId) {
    fetch('/api/trade/status/' + encodeURIComponent(tradeId), {
      credentials: 'include', headers: { 'X-Requested-With': 'XMLHttpRequest' }
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (!d || d.ok === false) {
        // The trade is gone or is not ours. Stop following it rather than
        // asking forever.
        stop(); forget(); return;
      }
      render(d);
      if (TERMINAL.indexOf(d.state) !== -1) {
        stop();
        forget();
        if (d.state === 'COMPLETED' && typeof window._toast === 'function') {
          window._toast('Trade complete', true);
        }
        return;
      }
      _pollTimer = setTimeout(function () { poll(tradeId); }, POLL_MS);
    }).catch(function () {
      // A failed poll says nothing about the trade. Try again.
      _pollTimer = setTimeout(function () { poll(tradeId); }, POLL_MS * 2);
    });
  }

  function stop() {
    if (_pollTimer) { clearTimeout(_pollTimer); _pollTimer = null; }
    _watching = '';
  }

  function watch(tradeId, meta) {
    if (!tradeId) return;
    if (_watching === tradeId) return;   // already following this one
    stop();
    _watching = tradeId;
    remember(tradeId, meta);
    poll(tradeId);
  }

  /* ── starting one ── */
  function execute(quoteId, meta) {
    if (!quoteId) return Promise.resolve(false);
    return fetch('/api/trade/execute', {
      method: 'POST', credentials: 'include', headers: headers(),
      // The quote id IS the idempotency key on the server when the client
      // sends none, so pressing Buy twice on one quote cannot bridge twice.
      body: JSON.stringify({ quote_id: quoteId })
    }).then(function (r) { return r.json().then(function (d) { return { r: r, d: d }; }); })
      .then(function (res) {
        var d = res.d || {};
        if (d.code === 'NATIVE_GAS_REQUIRED') {
          if (typeof window._toast === 'function') window._toast(d.msg, false);
          return false;
        }
        if (!res.r.ok || d.ok === false) {
          if (typeof window._toast === 'function') {
            window._toast(d.msg || d.failure_reason || 'Trade could not start', false);
          }
          return false;
        }
        if (d.trade_id) { watch(d.trade_id, meta); render(d); }
        return true;
      }).catch(function () {
        if (typeof window._toast === 'function') {
          window._toast('Network error — the trade was not started', false);
        }
        return false;
      });
  }

  function dismiss() {
    var el = document.getElementById('orca-cc-progress');
    if (el) el.style.display = 'none';
    // Deliberately does NOT stop the poll or forget the trade: hiding a
    // banner is not cancelling a trade, and the trade is still running.
  }

  /* ── a refresh reconnects, it does not start again ── */
  function resume() {
    var v = remembered();
    if (v && v.trade_id) watch(v.trade_id, v);
  }

  window.OrcaCrossChain = {
    execute: execute, watch: watch, dismiss: dismiss, resume: resume,
    stepIndex: stepIndex, STEPS: STEPS, TERMINAL: TERMINAL
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', resume);
  } else {
    resume();
  }
})();
