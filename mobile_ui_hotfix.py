"""Route-scoped mobile UI enhancement loader.

Only the current screen receives its own assets. One auth controller owns the
Connect/profile state; retired controllers no longer issue duplicate requests.
"""


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_mobile_ui_hotfix_installed', False):
        return
    app._orca_mobile_ui_hotfix_installed = True
    marker = 'data-orca-mobile-hotfix="2"'
    shared_tags = (
        '<link rel="stylesheet" href="/static/mobile-share-menu-fix.css?v=4" ' + marker + '>'
        '<script src="/static/mobile-share-menu-fix.js?v=5" defer ' + marker + '></script>'
        '<script src="/static/mobile-connect-button.js?v=7" defer ' + marker + '></script>'
    )
    home_tags = (
        '<script src="/static/home-start-trading-route.js?v=2" defer ' + marker + '></script>'
        '<link rel="stylesheet" href="/static/home-feed-chart-redesign.css?v=2" ' + marker + '>'
        '<script src="/static/home-feed-chart-redesign.js?v=3" defer ' + marker + '></script>'
    )
    live_market_tags = (
        '<link rel="stylesheet" href="/static/live-market-mobile-drawer-fix.css?v=1" ' + marker + '>'
    )

    @app.after_request
    def _inject_mobile_ui_hotfix(response):
        try:
            if response.status_code != 200 or response.mimetype != 'text/html':
                return response
            body = response.get_data(as_text=True)
            if marker in body:
                return response
            path = dashboard_module.request.path.rstrip('/') or '/'
            tags = shared_tags
            if path == '/':
                tags += home_tags
            elif path == '/live-market':
                tags += live_market_tags
            body = body.replace('</head>', tags + '</head>', 1) if '</head>' in body else tags + body
            response.set_data(body)
            response.content_length = len(response.get_data())
        except Exception as exc:
            app.logger.warning('mobile UI injection skipped: %s', exc)
        return response
