"""Production security hardening for OrcAgent.

Adds defense-in-depth around browser execution, session cookies, cross-site
mutation requests and malformed/oversized request targets without changing
the application's route/business logic.
"""
from __future__ import annotations

import re
import secrets
from urllib.parse import urlsplit

from flask import g, jsonify, request

_SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})
_BLOCKED_METHODS = frozenset({'TRACE', 'CONNECT'})
_ALLOWED_HOSTS = frozenset({'orcagent.fun', 'www.orcagent.fun'})
_MAX_PATH = 4096
_MAX_QUERY = 16384
_SCRIPT_TAG_RE = re.compile(r'<script(?![^>]*\bnonce=)([^>]*)>', re.I)


def _csp(nonce: str) -> str:
    # Legacy onclick/onchange attributes still exist across the UI, so
    # script-src-attr keeps unsafe-inline temporarily. Script ELEMENTS are now
    # nonce-gated: injected <script> blocks cannot execute without the random
    # per-response nonce that only the server adds.
    return '; '.join([
        "default-src 'self'",
        "base-uri 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "script-src 'self' https://unpkg.com",
        f"script-src-elem 'self' https://unpkg.com 'nonce-{nonce}'",
        "script-src-attr 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' data: https://fonts.gstatic.com",
        "img-src 'self' data: blob: https:",
        "media-src 'self' blob: https:",
        "connect-src 'self' https://api.binance.com https://api.mainnet-beta.solana.com https://mainnet.helius-rpc.com https://api.jup.ag https://quote-api.jup.ag https://api.dexscreener.com https://dexscreener.com https://api.helius.xyz wss: ws:",
        "frame-src 'self' https://dexscreener.com",
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
        g.orca_csp_nonce = secrets.token_urlsafe(18)
        method = (request.method or '').upper()
        if method in _BLOCKED_METHODS:
            return jsonify({'error': 'Method not allowed'}), 405

        path = request.path or ''
        query_bytes = request.query_string or b''
        if len(path) > _MAX_PATH or len(query_bytes) > _MAX_QUERY:
            return jsonify({'error': 'Request target too long'}), 414

        query = query_bytes.decode('latin-1', 'ignore')
        raw_target = path + ('?' + query if query else '')
        normalized = raw_target.lower()
        if (
            '\x00' in raw_target or '\r' in raw_target or '\n' in raw_target
            or '%00' in normalized or '%0d' in normalized or '%0a' in normalized
        ):
            return jsonify({'error': 'Invalid request target'}), 400

        if method in _SAFE_METHODS:
            return None

        fetch_site = (request.headers.get('Sec-Fetch-Site') or '').strip().lower()
        if fetch_site == 'cross-site':
            return jsonify({'error': 'Cross-site request blocked'}), 403

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
        nonce = getattr(g, 'orca_csp_nonce', '') or secrets.token_urlsafe(18)
        response.headers['Content-Security-Policy'] = _csp(nonce)
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        response.headers.setdefault('X-Permitted-Cross-Domain-Policies', 'none')
        response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
        response.headers.setdefault('Cross-Origin-Opener-Policy', 'same-origin')
        response.headers.setdefault('Cross-Origin-Resource-Policy', 'same-site')
        response.headers.setdefault('Origin-Agent-Cluster', '?1')
        response.headers.setdefault('X-DNS-Prefetch-Control', 'off')
        response.headers.pop('X-Powered-By', None)

        if request.path.startswith('/api/'):
            response.headers.setdefault('Cache-Control', 'no-store')

        if response.status_code == 200 and response.mimetype == 'text/html':
            try:
                body = response.get_data(as_text=True)
                # Give every script element the server-only nonce. Event-handler
                # attributes remain covered by script-src-attr during the legacy
                # migration, but injected script blocks now fail CSP.
                body = _SCRIPT_TAG_RE.sub(
                    lambda m: '<script nonce="' + nonce + '"' + m.group(1) + '>', body
                )
                if 'data-orca-security-runtime="1"' not in body:
                    runtime = (
                        '<script nonce="' + nonce + '" src="/static/security-runtime.js?v=4" '
                        'defer data-orca-security-runtime="1"></script>'
                    )
                    if '</head>' in body:
                        body = body.replace('</head>', runtime + '</head>', 1)
                    else:
                        body = runtime + body
                response.set_data(body)
                response.content_length = len(response.get_data())
            except Exception as exc:
                app.logger.warning('security runtime/CSP nonce injection skipped: %s', exc)
        return response
