"""Remove the legacy browser-visible API shared secret boundary.

A value rendered into HTML/JavaScript cannot be a server secret: every signed-in
browser, extension and XSS sink can read it. OrcAgent already has the correct browser
boundaries -- authenticated wallet/session, CSRF and route/object authorization -- so
production disables the legacy shared-secret requirement for browser routes and
scrubs the historical value from HTML as a final safety net.

Because this credential was historically delivered to browsers, it must be treated as
compromised. The legacy environment variable is therefore removed from the running
process after import too; no later code should accidentally revive it as an auth factor.
This module never logs or returns the old value.
"""
from __future__ import annotations

import os


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_browser_shared_secret_hardening_installed', False):
        return
    app._orca_browser_shared_secret_hardening_installed = True

    # Capture only so an already-rendered legacy page can be scrubbed below.
    # Do not persist, print or expose this value anywhere else.
    legacy_secret = str(
        getattr(dashboard_module, 'API_SHARED_SECRET', '')
        or os.environ.get('API_SHARED_SECRET', '')
        or ''
    )

    # dashboard.py's mutation guard and template context both read this module
    # value. An empty value makes browser requests rely on session + CSRF +
    # authorization instead of a credential that was shipped to the browser.
    if hasattr(dashboard_module, 'API_SHARED_SECRET'):
        dashboard_module.API_SHARED_SECRET = ''
    app.config['API_SHARED_SECRET'] = ''
    os.environ.pop('API_SHARED_SECRET', None)

    @app.after_request
    def _never_emit_legacy_shared_secret(response):
        if not legacy_secret or response.mimetype != 'text/html':
            return response
        try:
            body = response.get_data(as_text=True)
            if legacy_secret in body:
                body = body.replace(legacy_secret, '')
                response.set_data(body)
                response.content_length = len(response.get_data())
                response.headers['Cache-Control'] = 'no-store'
                app.logger.error('blocked legacy API shared secret from HTML response')
        except Exception:
            # If the response cannot be safely inspected, fail closed instead
            # of sending a page that may contain the server-wide credential.
            response.set_data(b'Security response blocked')
            response.status_code = 500
            response.headers['Content-Type'] = 'text/plain; charset=utf-8'
            response.headers['Cache-Control'] = 'no-store'
            response.content_length = len(response.get_data())
        return response
