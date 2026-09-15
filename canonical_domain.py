"""Keep OrcAgent on one canonical public host and reject Host-header spoofing.

Every request that reaches Flask through www.orcagent.fun is permanently redirected
to https://orcagent.fun while preserving path/query. Unknown Host values are rejected
before route handlers can use them to construct absolute links, OAuth callbacks or
security-sensitive origins.
"""
from urllib.parse import urlsplit, urlunsplit

from flask import abort, redirect, request


_INSTALLED = False
_CANONICAL_HOST = "orcagent.fun"
_ALIAS_HOSTS = {"www.orcagent.fun"}
_LOCAL_HOSTS = {"127.0.0.1", "localhost"}
_ALLOWED_HOSTS = {_CANONICAL_HOST, *_ALIAS_HOSTS, *_LOCAL_HOSTS}


def _host_only(value: str) -> str:
    text = str(value or '').strip().lower().rstrip('.')
    if text.startswith('['):
        end = text.find(']')
        return text[1:end] if end > 0 else text
    return text.split(':', 1)[0]


def install(dashboard_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    app = dashboard_module.app

    @app.before_request
    def _canonicalize_public_host():
        host = _host_only(request.host)
        if host not in _ALLOWED_HOSTS:
            app.logger.warning('rejected untrusted Host header')
            abort(400)
        if host not in _ALIAS_HOSTS:
            return None

        parts = urlsplit(request.url)
        target = urlunsplit(("https", _CANONICAL_HOST, parts.path, parts.query, ""))
        return redirect(target, code=308)
