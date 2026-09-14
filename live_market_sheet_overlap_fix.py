"""Mobile Live Market execution-sheet layout guard.

Prevents the ticket stats, quick percentage buttons and keypad from collapsing
into each other on shorter iPhone viewports. This is presentation-only: no
trade routing, amounts, quotes, fees or execution behaviour is changed.
"""

_CSS = r'''
<style data-orca-live-sheet-overlap-fix="1">
@media (max-width: 767px) {
  body.oa-live-v2 .pt-sheet {
    overflow-y: auto !important;
    overflow-x: hidden !important;
    -webkit-overflow-scrolling: touch !important;
    overscroll-behavior-y: contain;
  }

  /* The amount/ticket block must own enough height for the 3-column stats.
     Previously it was flex:1 and was squeezed by the keypad/footer, causing
     24H MOVE / LIQUIDITY / VOLUME to sit underneath the percentage row. */
  body.oa-live-v2 .pt-sheet-mid {
    flex: 0 0 auto !important;
    min-height: 205px !important;
    height: auto !important;
    overflow: visible !important;
    padding-bottom: 14px !important;
  }

  body.oa-live-v2 .pt-ticket {
    height: auto !important;
    min-height: 185px !important;
    overflow: visible !important;
    align-content: start !important;
  }

  body.oa-live-v2 .pt-ticket-stats {
    position: static !important;
    width: 100% !important;
    min-height: 48px !important;
    margin: 8px 0 0 !important;
    padding: 10px 0 0 !important;
    transform: none !important;
    clear: both !important;
    z-index: 1 !important;
  }

  body.oa-live-v2 .pt-sheet-pcts {
    position: static !important;
    flex: 0 0 auto !important;
    margin: 0 !important;
    padding: 8px 16px 12px !important;
    transform: none !important;
    clear: both !important;
    z-index: 2 !important;
    background: #060a0f !important;
  }

  body.oa-live-v2 #pt-keys,
  body.oa-live-v2 .pt-keys {
    position: static !important;
    flex: 0 0 auto !important;
    margin-top: 0 !important;
    transform: none !important;
    clear: both !important;
    z-index: 1 !important;
  }

  body.oa-live-v2 .pt-sheet-fees,
  body.oa-live-v2 .pt-fees,
  body.oa-live-v2 .pt-sheet-ft,
  body.oa-live-v2 .pt-slide {
    position: static !important;
    transform: none !important;
    flex-shrink: 0 !important;
  }
}

/* Extra breathing room on shorter iPhones: scrolling is preferable to
   overlapping controls or shrinking tap targets. */
@media (max-width: 767px) and (max-height: 760px) {
  body.oa-live-v2 .pt-sheet-mid { min-height: 190px !important; }
  body.oa-live-v2 .pt-ticket { min-height: 172px !important; }
}
</style>
'''


def install(d):
    if getattr(d, '_orca_live_sheet_overlap_fix_installed', False):
        return
    d._orca_live_sheet_overlap_fix_installed = True

    @d.app.after_request
    def _inject_live_sheet_overlap_fix(response):
        try:
            if response.status_code != 200 or response.mimetype != 'text/html':
                return response
            path = (d.request.path or '').rstrip('/') or '/'
            if path != '/live-market':
                return response
            body = response.get_data(as_text=True)
            if 'data-orca-live-sheet-overlap-fix="1"' in body:
                return response
            body = body.replace('</head>', _CSS + '</head>', 1) if '</head>' in body else _CSS + body
            response.set_data(body)
            response.content_length = len(response.get_data())
        except Exception as exc:
            d.app.logger.debug('live-market overlap CSS injection skipped: %s', exc)
        return response
