"""Small mobile UI hotfix loader.

Injects versioned mobile assets at response time so Safari/Phantom cannot keep
serving an older cached bottom-nav or clipped share menu after deploys.
"""


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_mobile_ui_hotfix_installed', False):
        return
    app._orca_mobile_ui_hotfix_installed = True

    marker = 'data-orca-mobile-hotfix="1"'
    tags = (
        '<link rel="stylesheet" href="/static/mobile-share-menu-fix.css?v=4" '
        + marker + '>'
        '<script src="/static/mobile-share-menu-fix.js?v=5" defer '
        + marker + '></script>'
        '<script src="/static/mobile-nav-post-force.js?v=2" defer '
        + marker + '></script>'
        '<script src="/static/navbar-connect-state.js?v=5" defer '
        + marker + '></script>'
        '<script src="/static/mobile-connect-button.js?v=4" defer '
        + marker + '></script>'
    )

    @app.after_request
    def _inject_mobile_ui_hotfix(response):
        try:
            if response.status_code != 200 or response.mimetype != 'text/html':
                return response
            body = response.get_data(as_text=True)
            if marker in body:
                return response
            if '</head>' in body:
                body = body.replace('</head>', tags + '</head>', 1)
            else:
                body = tags + body
            response.set_data(body)
            response.content_length = len(response.get_data())
        except Exception as exc:
            app.logger.warning('mobile UI hotfix injection skipped: %s', exc)
        return response
