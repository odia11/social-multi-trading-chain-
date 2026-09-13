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

            css_assets = [
                ('messages-premium-v2.css', '/static/messages-premium-v2.css?v=1'),
                ('messages-premium-v3.css', '/static/messages-premium-v3.css?v=2'),
                ('messages-composer-v4.css', '/static/messages-composer-v4.css?v=3'),
                ('messages-thread-v5.css', '/static/messages-thread-v5.css?v=1'),
                ('messages-thread-v6.css', '/static/messages-thread-v6.css?v=2'),
            ]
            for marker, href in css_assets:
                if marker not in body and '</head>' in body:
                    body = body.replace('</head>', f'<link rel="stylesheet" href="{href}">\n</head>', 1)

            js_assets = [
                ('messages-premium-v3.js', '/static/messages-premium-v3.js?v=1'),
                ('messages-composer-v4.js', '/static/messages-composer-v4.js?v=3'),
                ('messages-thread-v5.js', '/static/messages-thread-v5.js?v=2'),
                ('messages-thread-v6.js', '/static/messages-thread-v6.js?v=3'),
            ]
            for marker, src in js_assets:
                if marker not in body and '</body>' in body:
                    body = body.replace('</body>', f'<script src="{src}" defer></script>\n</body>', 1)

            response.set_data(body)
            response.content_length = len(response.get_data())
        except Exception as exc:
            app.logger.warning('messages premium UI injection skipped: %s', exc)
        return response
