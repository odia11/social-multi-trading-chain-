"""Production security hardening for OrcAgent.

This layer is intentionally narrow: it adds browser/security headers, limits
request size, hardens session-cookie defaults, and rejects explicit cross-site
state-changing requests without changing existing route/business logic.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from flask import jsonify, request

_SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS', 'TRACE'})
_ALLOWED_HOSTS = frozenset({'orcagent.fun', 'www.orcagent.fun'})

# The application currently contains legacy inline JS/CSS, so 'unsafe-inline'
# is retained for compatibility. The remaining directives still materially
# reduce exploit surface (no plugins/objects, no framing, no hostile base tag,
# restricted network/image/font/form destinations). New code should keep
# moving inline scripts/styles into static files so these two allowances can
# eventually be removed.
_CSP = '; '.join([
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "script-src 'self' 'unsafe-inline' https://unpkg.com",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' data: https://fonts.gstatic.com",
    "img-src 'self' data: blob: https:",
    "media-src 'self' blob: https:",
    "connect-src 'self' https://api.binance.com https://api.mainnet-beta.solana.com https://mainnet.helius-rpc.com https://api.jup.ag https://quote-api.jup.ag https://api.dexscreener.com https://dexscreener.com https://api.helius.xyz wss: ws:",
    "worker-src 'self' blob:",
    "manifest-src 'self'",
    "upgrade-insecure-requests",
])


def _origin_host(value: str) -> str:
    try:
        return (urlsplit(value).hostname or '').lower().rstrip('.')
    except Exception:
        return ''


def _request_host() -> str:
    # request.host may contain a port; split it safely without trusting
    # X-Forwarded-Host directly here.
    return (request.host.split(':', 1)[0] or '').lower().rstrip('.')


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_security_hardening_installed', False):
        return
    app._orca_security_hardening_installed = True

    # Covers image/data uploads while preventing accidental/unbounded request
    # bodies from becoming a memory/DoS vector. Existing OG image handling is
    # capped at 8 MiB, so 12 MiB leaves transport/JSON overhead room.
    app.config['MAX_CONTENT_LENGTH'] = min(
        int(app.config.get('MAX_CONTENT_LENGTH') or 12 * 1024 * 1024),
        12 * 1024 * 1024,
    )
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    @app.before_request
    def _security_request_guard():
        # Reject NUL/control characters before they reach application parsers,
        # logs, filesystem-ish helpers, or downstream HTTP clients.
        raw_target = (request.path or '') + '?' + (request.query_string.decode('latin-1', 'ignore') if request.query_string else '')
        if '\x00' in raw_target or '\r' in raw_target or '\n' in raw_target:
            return jsonify({'error': 'Invalid request target'}), 400

        if request.method in _SAFE_METHODS:
            return None

        # Same-origin check as an additional CSRF boundary. Browsers send
        # Origin on fetch/XHR POSTs; non-browser clients that omit Origin stay
        # compatible. Explicit foreign/null origins are rejected.
        origin = (request.headers.get('Origin') or '').strip()
        if origin:
            origin_host = _origin_host(origin)
            host = _request_host()
            allowed = set(_ALLOWED_HOSTS)
            if host:
                allowed.add(host)
            if not origin_host or origin_host not in allowed:
                return jsonify({'error': 'Cross-site request blocked'}), 403

        # Mutation APIs should not accept arbitrary browser form/text payloads
        # when a caller claims to be JSON. Flask will still handle legitimate
        # multipart/form endpoints outside /api/ normally.
        if request.path.startswith('/api/') and request.content_length:
            ctype = (request.mimetype or '').lower()
            if ctype == 'text/plain':
                return jsonify({'error': 'Unsupported content type'}), 415
        return None

    @app.after_request
    def _security_headers(response):
        # setdefault preserves any stricter route-specific policy.
        response.headers.setdefault('Content-Security-Policy', _CSP)
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        response.headers.setdefault('X-Permitted-Cross-Domain-Policies', 'none')
        response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')

        # Avoid leaking framework/version details through permissive defaults.
        response.headers.pop('X-Powered-By', None)

        # JSON/API responses should never be MIME-sniffed or cached by a
        # shared intermediary when authenticated cookies may be involved.
        if request.path.startswith('/api/'):
            response.headers.setdefault('Cache-Control', 'no-store')
        return response
