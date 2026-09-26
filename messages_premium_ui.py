"""Load the approved Messages presentation as two ordered bundles.

The bundle order matches the previous assets, preserving cascade and behaviour
with nine fewer HTTP requests.
"""


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_messages_ui_installed', False):
        return
    app._orca_messages_ui_installed = True

    @app.after_request
    def _messages_ui(response):
        try:
            if response.status_code != 200 or response.mimetype != 'text/html':
                return response
            body = response.get_data(as_text=True)
            if '<title>Messages — OrcAgent</title>' not in body:
                return response
            if 'messages-ui.css' not in body and '</head>' in body:
                body = body.replace('</head>', '<link rel="stylesheet" href="/static/messages-ui.css?v=1">\n</head>', 1)
            # The inbox (chat list) design; loaded last so it wins.
            if 'messages-inbox.css' not in body and '</head>' in body:
                body = body.replace('</head>', '<link rel="stylesheet" href="/static/messages-inbox.css?v=1">\n</head>', 1)
            if 'messages-ui.js' not in body and '</body>' in body:
                body = body.replace('</body>', '<script src="/static/messages-ui.js?v=1" defer></script>\n</body>', 1)
            response.set_data(body)
            response.content_length = len(response.get_data())
        except Exception as exc:
            app.logger.warning('messages UI injection skipped: %s', exc)
        return response
