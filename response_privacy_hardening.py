"""Defense-in-depth against accidental secret fields in JSON API responses.

Authentication endpoints are allowed to return the short-lived values their clients
actually need. Everywhere else, database/internal credential fields are stripped
recursively before JSON leaves the process.
"""
from __future__ import annotations

import json

from flask import request

_ALWAYS_SECRET = {
    'private_key', 'privatekey', 'encrypted_private_key', 'encrypted_private_key_bsc',
    'encrypted_private_key_evm', 'token_hash', 'password', 'password_hash',
    'api_secret', 'client_secret', 'secret_key', 'encryption_key', 'recovery_token',
    'refresh_token', 'access_token', 'signature_secret',
}
_AUTH_ALLOWED_PATHS = {
    '/api/wallet/set', '/api/session/remember', '/api/session/resume',
    '/api/pair/claim', '/api/csrf',
}


def _clean(value, allow_auth=False):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            low = str(key).lower()
            if low in _ALWAYS_SECRET or low.startswith('encrypted_private_key'):
                continue
            if not allow_auth and low in {'device_token', 'csrf_token'}:
                continue
            out[key] = _clean(item, allow_auth)
        return out
    if isinstance(value, list):
        return [_clean(v, allow_auth) for v in value]
    return value


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_response_privacy_installed', False):
        return
    app._orca_response_privacy_installed = True

    @app.after_request
    def _redact_api_response(response):
        if not request.path.startswith('/api/') or not response.is_json:
            return response
        try:
            payload = response.get_json(silent=True)
            if payload is None:
                return response
            cleaned = _clean(payload, request.path in _AUTH_ALLOWED_PATHS)
            if cleaned != payload:
                body = json.dumps(cleaned, separators=(',', ':'), ensure_ascii=False, default=str).encode('utf-8')
                response.set_data(body)
                response.headers['Content-Type'] = 'application/json; charset=utf-8'
                response.content_length = len(body)
        except Exception as exc:
            app.logger.warning('API response privacy filter failed: %s', exc)
        return response
