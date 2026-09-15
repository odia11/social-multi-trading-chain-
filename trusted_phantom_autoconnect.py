"""Inject the silent trusted Phantom reconnect helper on HTML responses."""


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_trusted_phantom_autoconnect_installed', False):
        return
    app._orca_trusted_phantom_autoconnect_installed = True

    marker = 'data-orca-trusted-phantom="1"'
    tag = (
        '<script src="/static/trusted-phantom-autoconnect.js?v=1" defer '
        + marker + '></script>'
    )

    @app.after_request
    def _inject_trusted_phantom_autoconnect(response):
        try:
            if response.status_code != 200 or response.mimetype != 'text/html':
                return response
            body = response.get_data(as_text=True)
            if marker in body:
                return response
            if '</head>' in body:
                body = body.replace('</head>', tag + '</head>', 1)
            else:
                body = tag + body
            response.set_data(body)
            response.content_length = len(response.get_data())
        except Exception as exc:
            app.logger.warning('trusted Phantom autoconnect injection skipped: %s', exc)
        return response
