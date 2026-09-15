"""Make Live Market's BUY sheet match OrcAgent's automatic funding model.

The backend already auto-bridges a buy when the destination chain does not
hold enough of its stable asset.  The Live Market sheet nevertheless used
only the destination-chain balance and disabled the slider before the request
could ever reach that backend path.  That was especially visible on Robinhood
Chain: a user could have USDC elsewhere in the OrcAgent wallet, see the money
in the shared header, yet the HOOD buy sheet said $0 available.

For BUYs, the amount controls must use /api/wallet/usdc-summary.total_usdc --
the amount the product presents as spendable USDC across the wallet.  SELLs
remain chain/position-specific and are untouched.
"""


def install(d):
    app = d.app
    if getattr(app, '_orca_live_market_pooled_buy_balance_installed', False):
        return
    app._orca_live_market_pooled_buy_balance_installed = True

    marker = 'id="oa-pooled-buy-balance"'
    script = r'''<script id="oa-pooled-buy-balance">
(function(){
  function pooledBalance(summary){
    var total = Number(summary && summary.total_usdc);
    if(Number.isFinite(total) && total >= 0) return total;
    var n = Number(summary && summary.solana_usdc) || 0;
    var evm = (summary && summary.evm_chains) || {};
    ['bsc','base','arbitrum','polygon','robinhood'].forEach(function(c){
      n += Number(evm[c]) || 0;
    });
    return n;
  }

  function installOverride(){
    if(typeof window._paintSheet !== 'function') return false;
    // A BUY can auto-bridge from another funded chain.  Do not use the
    // destination balance as a client-side veto; that prevented the request
    // from ever reaching _maybe_start_auto_bridge_for_buy on the server.
    window._loadSheetBalance = function(_chain){
      var now = Date.now();
      var use = function(d){
        window._sheetAvail = pooledBalance(d);
        window._paintSheet();
      };
      if(window._availCache && window._availCache.data &&
         now - window._availCache.t < 12000){
        use(window._availCache.data);
        return;
      }
      fetch('/api/wallet/usdc-summary', {credentials:'include'})
        .then(function(r){ return r.json(); })
        .then(function(d){
          if(!d || !d.ok) return;
          window._availCache = {t:Date.now(), data:d};
          use(d);
        })
        .catch(function(){});
    };
    return true;
  }

  if(!installOverride()){
    document.addEventListener('DOMContentLoaded', installOverride, {once:true});
    setTimeout(installOverride, 0);
  }
})();
</script>'''

    @app.after_request
    def _inject_pooled_buy_balance(response):
        try:
            if response.status_code != 200 or response.mimetype != 'text/html':
                return response
            body = response.get_data(as_text=True)
            if marker in body or '/api/wallet/usdc-summary' not in body:
                return response
            # Scope this to pages that actually contain the shared Live Market
            # buy sheet.  The marker is stable across desktop/mobile.
            if 'pt-sheet' not in body or 'confirmBuy' not in body:
                return response
            body = body.replace('</body>', script + '\n</body>', 1) if '</body>' in body else body + script
            response.set_data(body)
            response.headers['Content-Length'] = str(len(response.get_data()))
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        except Exception as exc:
            app.logger.debug('pooled Live Market balance injection skipped: %s', exc)
        return response
