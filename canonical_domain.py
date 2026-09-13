"""Keep OrcAgent on one canonical public host.

Every request that reaches Flask through www.orcagent.fun is permanently
redirected to https://orcagent.fun while preserving path and query string.
This is deliberately app-level too, so the canonical host survives nginx/
certbot config drift on future deploys.
"""
from urllib.parse import urlsplit, urlunsplit

from flask import redirect, request


_INSTALLED = False
_CANONICAL_HOST = "orcagent.fun"
_ALIAS_HOSTS = {"www.orcagent.fun"}


def install(dashboard_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    app = dashboard_module.app

    @app.before_request
    def _canonicalize_public_host():
        host = (request.host or "").split(":", 1)[0].lower().rstrip(".")
        if host not in _ALIAS_HOSTS:
            return None

        # Keep the exact path + query. 308 is permanent like 301, but unlike
        # 301 it never changes a POST into a GET if an API call ever arrives
        # through the www hostname.
        parts = urlsplit(request.url)
        target = urlunsplit(("https", _CANONICAL_HOST, parts.path, parts.query, ""))
        return redirect(target, code=308)
