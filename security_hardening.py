"""Production security hardening for OrcAgent.

This layer is intentionally narrow: it adds browser/security headers, limits
request size, hardens session-cookie defaults, rejects explicit cross-site
state-changing requests, and injects the client-side DOM hardening guard.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from flask import jsonify, request

_SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS', 'TRACE'})
_ALLOWED_HOSTS = frozenset({'orcagent.fun', 'www.orcagent.fun'})
_RUNTIME_TAG = '<script src="/static/security-runtime.js?v=1" defer data-orca-security-runtime="1"></script>'

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
    return (request.host.split(':', 1)[0] or '').lower().rstrip('.')


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_security_hardening_installed', False):
        return
    app._orca_security_hardening_installed = True

    app.config['MAX_CONTENT_LENGTH'] = min(
        int(app.config.get('MAX_CONTENT_LENGTH') or 12 * 1024 * 1024),
        12 * 1024 * 1024,
    )
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    @app.before_request
    def _security_request_guard():
        raw_target = (request.path or '') + '?' + (request.query_string.decode('latin-1', 'ignore') if request.query_string else '')
        if '\x00' in raw_target or '\r' in raw_target or '\n' in raw_target:
            return jsonify({'error': 'Invalid request target'}), 400

        if request.method in _SAFE_METHODS:
            return None

        # Same-origin check as an additional CSRF boundary. Requests with no
        # Origin remain compatible with CLI/server clients; explicit foreign
        # or opaque/null browser origins are denied.
        origin = (request.headers.get('Origin') or '').strip()
        if origin:
            origin_host = _origin_host(origin)
            host = _request_host()
            allowed = set(_ALLOWED_HOSTS)
            if host:
                allowed.add(host)
            if not origin_host or origin_host not in allowed:
                return jsonify({'error': 'Cross-site request blocked'}), 403

        if request.path.startswith('/api/') and request.content_length:
            ctype = (request.mimetype or '').lower()
            if ctype == 'text/plain':
                return jsonify({'error': 'Unsupported content type'}), 415
        return None

    @app.after_request
    def _security_headers(response):
        response.headers.setdefault('Content-Security-Policy', _CSP)
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        response.headers.setdefault('X-Permitted-Cross-Domain-Policies', 'none')
        response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
        response.headers.pop('X-Powered-By', None)

        if request.path.startswith('/api/'):
            response.headers.setdefault('Cache-Control', 'no-store')

        # Loaded on every HTML page, after parsing. It neutralizes active URL
        # schemes in dynamically inserted nodes and replaces a legacy username
        # innerHTML sink in the copy-trading modal with text nodes.
        if response.status_code == 200 and response.mimetype == 'text/html':
            try:
                body = response.get_data(as_text=True)
                if 'data-orca-security-runtime="1"' not in body:
                    if '</head>' in body:
                        body = body.replace('</head>', _RUNTIME_TAG + '</head>', 1)
                    else:
                        body = _RUNTIME_TAG + body
                    response.set_data(body)
                    response.content_length = len(response.get_data())
            except Exception as exc:
                app.logger.warning('security runtime injection skipped: %s', exc)
        return response
