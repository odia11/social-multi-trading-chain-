// ── INSUFFICIENT SOL BALANCE MODAL ──────────────────────────────────────────
// Shared by dashboard.html (bot start) and messages.html (copy trade) — pairs
// with templates/_low_balance_modal.html. Keep this the single implementation
// so desktop and mobile never drift into separate variants.
let _lbDepositAddr = null;

function showLowBalanceModal(data){
  _lbDepositAddr = data.trading_wallet || null;
  // The bot start gate reports in the currency it trades with (USDC);
  // copy trading still reports SOL and omits `currency`.
  const ccy = data.currency === 'USDC' ? 'USDC' : 'SOL';
  const dp = ccy === 'USDC' ? 2 : 4;
  const cur = typeof data.current === 'number' ? data.current : data.current_sol;
  const req = typeof data.required === 'number' ? data.required : data.required_sol;
  const title = document.getElementById('lb-title');
  if (title) title.textContent = '⚠ Insufficient ' + ccy + ' Balance';
  document.getElementById('lb-current').textContent  = (typeof cur === 'number' ? cur.toFixed(dp) : '—') + ' ' + ccy;
  document.getElementById('lb-required').textContent  = (typeof req === 'number' ? req.toFixed(dp) : '—') + ' ' + ccy;
  document.getElementById('lb-addr-text').textContent = _lbDepositAddr || '—';
  document.getElementById('lb-copy-msg').textContent  = '';
  document.getElementById('lb-copy-btn').textContent  = '📋';
  document.getElementById('low-balance-modal').classList.add('open');
}

function closeLowBalanceModal(){
  document.getElementById('low-balance-modal').classList.remove('open');
}

function copyLowBalanceAddr(){
  if (!_lbDepositAddr) return;
  const copyFallback = () => {
    const ta = document.createElement('textarea');
    ta.value = _lbDepositAddr;
    ta.style.cssText = 'position:fixed;opacity:0;pointer-events:none';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch(_) {}
    document.body.removeChild(ta);
  };
  const done = () => {
    document.getElementById('lb-copy-msg').textContent = '✓ Copied to clipboard';
    document.getElementById('lb-copy-btn').textContent = '✓';
    setTimeout(() => {
      document.getElementById('lb-copy-msg').textContent = '';
      document.getElementById('lb-copy-btn').textContent = '📋';
    }, 2000);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(_lbDepositAddr).then(done).catch(() => { copyFallback(); done(); });
  } else {
    copyFallback(); done();
  }
}
