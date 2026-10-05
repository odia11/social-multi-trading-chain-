
// Manual override: exact mint, explicit confirmation, no optimistic sale.
var _ltSelling = false;
document.getElementById('lt-open').addEventListener('click', function(event){
  var button = event.target.closest('[data-sell-mint]');
  if(!button || _ltSelling) return;
  document.getElementById('lt-sell-mint').value = button.dataset.sellMint;
  document.getElementById('lt-sell-title').textContent = 'Sell $' + button.dataset.sellSymbol + '?';
  document.getElementById('lt-sell-error').textContent = '';
  document.getElementById('lt-sell-dialog').showModal();
});
document.getElementById('lt-sell-confirm').addEventListener('click', async function(){
  if(_ltSelling) return;
  _ltSelling = true;
  this.disabled = true;
  this.textContent = 'Selling…';
  document.getElementById('lt-sell-cancel').disabled = true;
  try {
    var response = await fetch('/api/live-trades/sell', {method:'POST',
      credentials:'same-origin', headers:{'Content-Type':'application/json','X-CSRF-Token':_ltCsrf},
      body:JSON.stringify({mint_address:document.getElementById('lt-sell-mint').value})});
    var result = await response.json();
    if(!response.ok || !result.ok) throw new Error(result.msg || 'Sell could not be confirmed.');
    document.getElementById('lt-sell-dialog').close();
    document.getElementById('lt-feedback').textContent = result.msg + '. Your bot can continue trading.';
    await Promise.all([_ltPoll(),_ltPollBotStatus()]);
  } catch(error) { document.getElementById('lt-sell-error').textContent = error.message; }
  finally {
    _ltSelling = false;
    this.disabled = false;
    this.textContent = 'Sell all';
    document.getElementById('lt-sell-cancel').disabled = false;
  }
});
document.getElementById('lt-sell-cancel').addEventListener('click',function(){if(!_ltSelling)document.getElementById('lt-sell-dialog').close();});
document.getElementById('lt-sell-dialog').addEventListener('cancel',function(event){if(_ltSelling)event.preventDefault();});
