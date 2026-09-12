"""Wallet-page guidance for OrcAgent's one-USDC-across-chains model.

The trading balance is USDC across all supported chains. Users should not
have to understand bridge plumbing or guess which network to deposit on.
This small response adapter inserts one clear explanation immediately below
the wallet hero, without duplicating wallet.html or changing any balance or
trading logic.
"""


def install(appmod) -> None:
    if getattr(appmod, '_wallet_deposit_guidance_installed', False):
        return
    appmod._wallet_deposit_guidance_installed = True

    marker = '<!-- combined USDC balance across every chain this app trades on'
    notice = r'''
    <style>
      .wlt-usdc-guide{
        background:linear-gradient(135deg,rgba(247,185,85,.10),rgba(247,185,85,.035));
        border:1px solid rgba(247,185,85,.24);
        border-radius:16px;
        padding:15px 16px;
        display:flex;
        gap:12px;
        align-items:flex-start;
      }
      .wlt-usdc-guide-ic{
        width:34px;height:34px;border-radius:10px;flex:0 0 34px;
        display:flex;align-items:center;justify-content:center;
        background:rgba(247,185,85,.14);color:#f7b955;
        font-size:17px;font-weight:800;
      }
      .wlt-usdc-guide-title{font-size:13px;font-weight:700;color:#eef1f5;margin-bottom:4px}
      .wlt-usdc-guide-copy{font-size:11.5px;line-height:1.55;color:#8a919c}
      .wlt-usdc-guide-copy strong{color:#eef1f5;font-weight:650}
      .wlt-usdc-guide-fees{margin-top:6px;color:#6f7783}
      @media(max-width:720px){
        .wlt-usdc-guide{padding:14px;gap:10px;border-radius:14px}
        .wlt-usdc-guide-copy{font-size:11px}
      }
    </style>
    <div class="wlt-usdc-guide" role="note" aria-label="How USDC deposits work">
      <div class="wlt-usdc-guide-ic">$</div>
      <div>
        <div class="wlt-usdc-guide-title">Deposit USDC on any supported chain</div>
        <div class="wlt-usdc-guide-copy">
          Your USDC does <strong>not</strong> have to be on the same chain as the token you want to buy.
          OrcAgent automatically routes USDC to the required chain when needed.
          <div class="wlt-usdc-guide-fees">
            <strong>USDC = trading balance.</strong> SOL, ETH, BNB and POL are only used for network fees.
            Bridge and network costs are handled as part of the transaction; a network may still require its native gas balance to submit the route.
          </div>
        </div>
      </div>
    </div>
    '''

    @appmod.app.after_request
    def _inject_wallet_usdc_guidance(response):
        try:
            if appmod.request.path not in ('/wallet', '/portfolio'):
                return response
            if response.status_code != 200 or not response.is_json and 'text/html' not in (response.content_type or ''):
                return response
            html = response.get_data(as_text=True)
            if 'wlt-usdc-guide' in html or marker not in html:
                return response
            html = html.replace(marker, notice + '\n    ' + marker, 1)
            response.set_data(html)
            response.headers['Content-Length'] = str(len(response.get_data()))
        except Exception as exc:
            print(f'[wallet-guidance] injection skipped: {exc}', flush=True)
        return response
