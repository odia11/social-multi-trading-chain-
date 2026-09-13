"""Inject the approved OrcAgent premium inbox/chat UI onto the existing messages page.

The messaging routes, data model, swipe/delete logic, unread state, trade shares,
composer and mobile single-pane navigation remain owned by templates/messages.html.
This adapter only loads the new visual layer so functionality is not duplicated.
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
            from flask import request
            if response.status_code != 200 or response.mimetype != 'text/html':
                return response

            body = response.get_data(as_text=True)
            # Scope narrowly to the real messages template. This avoids touching
            # admin support threads or unrelated pages that also mention messages.
            if '<title>Messages — OrcAgent</title>' not in body:
                return response

            marker = 'messages-premium-v2.css'
            if marker not in body and '</head>' in body:
                asset = '<link rel="stylesheet" href="/static/messages-premium-v2.css?v=1">\n'
                body = body.replace('</head>', asset + '</head>', 1)
                response.set_data(body)
                response.content_length = len(response.get_data())
        except Exception as exc:
            app.logger.warning('messages premium UI injection skipped: %s', exc)
        return response
