"""Make Live Market BUY controls use OrcAgent's wallet-wide USDC balance.

Why the first hotfix did not work:
``static/live-market-pro.js`` is wrapped in an IIFE.  Its ``_loadSheetBalance``,
``_sheetAvail`` and ``_paintSheet`` names are closure-local, not ``window``
properties.  Trying to replace ``window._loadSheetBalance`` therefore changed
nothing; the real function kept reading only the destination-chain balance.

This version patches the data boundary instead.  On Live Market pages only,
and before the page controller starts, reads of ``/api/wallet/usdc-summary``
are normalised so each BUY-facing chain balance equals ``total_usdc``.  The
page's own closure-local code then naturally renders and validates the pooled
amount.  No trade endpoint is changed: the server still decides whether the
money is already on the destination or whether an automatic bridge/conversion
must run first.
"""


def install(d):
    app = d.app
    if getattr(app, '_orca_live_market_pooled_buy_balance_installed', False):
        return
    app._orca_live_market_pooled_buy_balance_installed = True

    marker = 'id="oa-pooled-buy-balance"'
    script = r'''<script id="oa-pooled-buy-balance">
(function(){
  'use strict';
  if(window.__orcaPooledBuyFetchInstalled) return;
  window.__orcaPooledBuyFetchInstalled = true;

  var originalFetch = window.fetch.bind(window);
  var CHAINS = ['bsc','base','arbitrum','polygon','robinhood'];

  function pooledTotal(d){
    var total = Number(d && d.total_usdc);
    if(Number.isFinite(total) && total >= 0) return total;
    var n = Number(d && d.solana_usdc) || 0;
    var evm = (d && d.evm_chains) || {};
    CHAINS.forEach(function(c){ n += Number(evm[c]) || 0; });
    return n;
  }

  function isSummaryRequest(input){
    var url = '';
    try{ url = typeof input === 'string' ? input : (input && input.url) || ''; }
    catch(e){ return false; }
    return url.indexOf('/api/wallet/usdc-summary') !== -1;
  }

  window.fetch = function(input, init){
    return originalFetch(input, init).then(function(resp){
      if(!isSummaryRequest(input) || !resp || !resp.ok) return resp;
      return resp.clone().json().then(function(body){
        if(!body || !body.ok) return resp;
        var total = pooledTotal(body);
        body.total_usdc = total;
        body.evm_chains = body.evm_chains || {};
        // Live Market's own _loadSheetBalance(chain) reads one of these
        // closure-locally.  Give that function the wallet-wide buying power;
        // the backend auto-bridge remains authoritative about where the funds
        // actually live and moves/converts them only after the user confirms.
        CHAINS.forEach(function(c){ body.evm_chains[c] = total; });
        body.solana_usdc = total;
        body.pooled_for_live_market_buy = true;

        var headers = new Headers(resp.headers);
        headers.set('Content-Type', 'application/json');
        headers.set('Cache-Control', 'no-store');
        return new Response(JSON.stringify(body), {
          status: resp.status,
          statusText: resp.statusText,
          headers: headers
        });
      }).catch(function(){ return resp; });
    });
  };
})();
</script>'''

    @app.after_request
    def _inject_pooled_buy_balance(response):
        try:
            if response.status_code != 200 or response.mimetype != 'text/html':
                return response
            body = response.get_data(as_text=True)
            if marker in body:
                return response
            # Only the Live Market trade sheet gets this behaviour.  Inject in
            # <head>, before live-market-pro.js can prefetch/cache the old
            # per-chain balances.
            if 'pt-sheet' not in body or 'live-market-pro' not in body:
                return response
            if '</head>' in body:
                body = body.replace('</head>', script + '\n</head>', 1)
            else:
                body = script + body
            response.set_data(body)
            response.headers['Content-Length'] = str(len(response.get_data()))
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        except Exception as exc:
            app.logger.debug('pooled Live Market balance injection skipped: %s', exc)
        return response
