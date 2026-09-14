"""Defense-in-depth against accidental secret fields in JSON API responses.

Authentication endpoints are allowed to return the short-lived values their clients
actually need. Everywhere else, database/internal credential fields are stripped
recursively before JSON leaves the process. If redaction itself ever fails, the
response is replaced with a generic error instead of leaking the original payload.
"""
from __future__ import annotations

import json

from flask import request

_ALWAYS_SECRET = {
    'private_key', 'privatekey', 'raw_private_key', 'wallet_private_key',
    'encrypted_private_key', 'encrypted_private_key_bsc', 'encrypted_private_key_evm',
    'mnemonic', 'seed', 'seed_phrase', 'wallet_seed',
    'token_hash', 'password', 'password_hash', 'api_secret', 'api_key', 'apikey',
    'client_secret', 'secret', 'secret_key', 'encryption_key', 'backup_encryption_key',
    'recovery_token', 'refresh_token', 'access_token', 'bearer_token',
    'authorization', 'signature_secret', 'vapid_private_key',
}
_AUTH_ALLOWED_PATHS = {
    '/api/wallet/set', '/api/session/remember', '/api/session/resume',
    '/api/pair/claim', '/api/csrf',
}


def _is_secret_field(key: object) -> bool:
    low = str(key).strip().lower()
    if low in _ALWAYS_SECRET:
        return True
    # Catch schema variations without blanketing ordinary token metadata such
    # as token_address/token_symbol. Private keys and secrets are never valid
    # API response fields.
    return (
        low.startswith('encrypted_private_key')
        or low.endswith('_private_key')
        or low.endswith('_password')
        or low.endswith('_secret')
    )


def _clean(value, allow_auth=False):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            low = str(key).lower()
            if _is_secret_field(key):
                continue
            if not allow_auth and low in {'device_token', 'csrf_token'}:
                continue
            out[key] = _clean(item, allow_auth)
        return out
    if isinstance(value, list):
        return [_clean(v, allow_auth) for v in value]
    return value


def _replace_with_blocked(response):
    body = b'{"error":"Response blocked by privacy guard"}'
    response.set_data(body)
    response.status_code = 500
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    response.headers['Cache-Control'] = 'no-store'
    response.content_length = len(body)
    return response


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
                response.headers['Cache-Control'] = 'no-store'
                response.content_length = len(body)
        except Exception as exc:
            # Privacy controls must fail closed. Returning the original body on
            # a sanitizer error would turn a defensive layer into a secret leak.
            app.logger.error('API response privacy filter blocked response: %s', type(exc).__name__)
            return _replace_with_blocked(response)
        return response
