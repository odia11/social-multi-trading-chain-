"""Inject a resilient exact-token deep-link opener into Live Market."""

_INSTALLED = False


def install(dashboard_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    app = dashboard_module.app

    @app.after_request
    def _inject_live_market_deeplink_fix(response):
        try:
            if response.status_code != 200 or response.mimetype != 'text/html':
                return response
            body = response.get_data(as_text=True)
            if '<title>Live Market — OrcAgent</title>' not in body:
                return response
            marker = 'live-market-deeplink-fix.js'
            if marker not in body and '</body>' in body:
                body = body.replace(
                    '</body>',
                    '<script src="/static/live-market-deeplink-fix.js?v=1" defer></script>\n</body>',
                    1,
                )
                response.set_data(body)
                response.content_length = len(response.get_data())
        except Exception as exc:
            app.logger.warning('live market deeplink fix injection skipped: %s', exc)
        return response
