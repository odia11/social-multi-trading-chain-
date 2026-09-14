"""Keep the shared mobile bottom navigation fully inside the iOS/PWA viewport.

The old nav used a fixed content height plus safe-area padding with
box-sizing:content-box. On iPhones this could make the real box taller than the
visible viewport allowance, pushing labels and the lower half of the footer
below the screen. This guard makes the safe area part of the declared height
and keeps every navigation item inside the visible box.
"""

_CSS = r'''
<style data-orca-mobile-footer-visibility-fix="1">
@media (max-width: 767px) {
  .oa-bottom-nav {
    position: fixed !important;
    left: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
    width: 100% !important;
    height: calc(92px + env(safe-area-inset-bottom, 0px)) !important;
    min-height: calc(92px + env(safe-area-inset-bottom, 0px)) !important;
    padding: 8px 14px calc(8px + env(safe-area-inset-bottom, 0px)) !important;
    box-sizing: border-box !important;
    align-items: start !important;
    overflow: visible !important;
    transform: none !important;
  }

  .oa-bottom-nav > a,
  .oa-bottom-nav > button {
    height: 68px !important;
    min-height: 68px !important;
    align-self: start !important;
    justify-content: center !important;
    padding: 4px 0 0 !important;
    margin: 0 !important;
    transform: none !important;
  }

  .oa-bottom-nav .oa-nav-label,
  .oa-bottom-nav > a > span:not(.pt-nb-badge),
  .oa-bottom-nav > button > span:not(.pt-nb-badge) {
    display: block !important;
    flex: 0 0 auto !important;
    line-height: 13px !important;
    min-height: 13px !important;
    visibility: visible !important;
    opacity: 1 !important;
  }

  .oa-bottom-nav .oa-trade-main {
    align-self: start !important;
    width: 76px !important;
    height: 76px !important;
    min-height: 76px !important;
    margin-top: -28px !important;
    padding: 0 !important;
  }

  .oa-bottom-nav .oa-trade-main span {
    top: 70px !important;
    line-height: 13px !important;
    min-height: 13px !important;
  }

  /* Reserve enough document space so the final page content never sits under
     the now-correctly-sized fixed footer. */
  body:not(.oa-trade-sheet-open) {
    padding-bottom: calc(126px + env(safe-area-inset-bottom, 0px)) !important;
  }
}
</style>
'''


def install(d):
    if getattr(d, '_orca_mobile_footer_visibility_fix_installed', False):
        return
    d._orca_mobile_footer_visibility_fix_installed = True

    @d.app.after_request
    def _inject_mobile_footer_visibility_fix(response):
        try:
            if response.status_code != 200 or response.mimetype != 'text/html':
                return response
            body = response.get_data(as_text=True)
            if 'data-orca-mobile-footer-visibility-fix="1"' in body:
                return response
            body = body.replace('</head>', _CSS + '</head>', 1) if '</head>' in body else _CSS + body
            response.set_data(body)
            response.content_length = len(response.get_data())
        except Exception as exc:
            d.app.logger.debug('mobile footer visibility fix skipped: %s', exc)
        return response
