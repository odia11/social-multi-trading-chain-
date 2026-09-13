"""Inject the approved OrcAgent premium inbox/chat UI onto the existing messages page.

Messaging routes, data and actions remain owned by templates/messages.html. This
adapter only loads the approved presentation/enhancement assets.
"""

_INSTALLED = False


def install(dashboard_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    app = dashboard_module.app

    @app.after_request
    def _messages_premium_ui(response):
        try:
            if response.status_code != 200 or response.mimetype != 'text/html':
                return response
            body = response.get_data(as_text=True)
            if '<title>Messages — OrcAgent</title>' not in body:
                return response

            if 'messages-premium-v2.css' not in body and '</head>' in body:
                body = body.replace('</head>', '<link rel="stylesheet" href="/static/messages-premium-v2.css?v=1">\n</head>', 1)
            if 'messages-premium-v3.css' not in body and '</head>' in body:
                body = body.replace('</head>', '<link rel="stylesheet" href="/static/messages-premium-v3.css?v=2">\n</head>', 1)
            if 'messages-composer-v4.css' not in body and '</head>' in body:
                body = body.replace('</head>', '<link rel="stylesheet" href="/static/messages-composer-v4.css?v=3">\n</head>', 1)
            if 'messages-thread-v5.css' not in body and '</head>' in body:
                body = body.replace('</head>', '<link rel="stylesheet" href="/static/messages-thread-v5.css?v=1">\n</head>', 1)

            if 'messages-premium-v3.js' not in body and '</body>' in body:
                body = body.replace('</body>', '<script src="/static/messages-premium-v3.js?v=1" defer></script>\n</body>', 1)
            if 'messages-composer-v4.js' not in body and '</body>' in body:
                body = body.replace('</body>', '<script src="/static/messages-composer-v4.js?v=3" defer></script>\n</body>', 1)
            if 'messages-thread-v5.js' not in body and '</body>' in body:
                body = body.replace('</body>', '<script src="/static/messages-thread-v5.js?v=1" defer></script>\n</body>', 1)

            response.set_data(body)
            response.content_length = len(response.get_data())
        except Exception as exc:
            app.logger.warning('messages premium UI injection skipped: %s', exc)
        return response
