"""Fail-fast checks for production cryptographic secrets.

This never prints secret values. It only rejects missing, obvious placeholder or
materially weak session/encryption secrets before the service starts accepting money.
"""
from __future__ import annotations

import os

_PLACEHOLDERS = {
    '', 'changeme', 'change-me', 'secret', 'dev', 'development', 'test',
    'your-secret-key', 'replace-me', 'todo', 'password',
}


def _bad_secret(value: str, minimum: int = 32) -> bool:
    raw = str(value or '').strip()
    return len(raw) < minimum or raw.lower() in _PLACEHOLDERS or len(set(raw)) < 6


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_secret_hygiene_installed', False):
        return
    app._orca_secret_hygiene_installed = True

    # DEV/test environments intentionally use throwaway values. Production may not.
    dev = str(os.getenv('DEV', '')).strip().lower() in {'1', 'true', 'yes', 'on'}
    testing = bool(app.config.get('TESTING'))
    if dev or testing:
        return

    secret_key = str(os.getenv('SECRET_KEY') or app.config.get('SECRET_KEY') or '')
    if _bad_secret(secret_key, 32):
        raise RuntimeError('SECRET_KEY is missing, placeholder-like, or too weak for production')

    encryption_key = str(os.getenv('ENCRYPTION_KEY') or '')
    if _bad_secret(encryption_key, 32):
        raise RuntimeError('ENCRYPTION_KEY is missing, placeholder-like, or too weak for production')

    # Prevent accidental debug exposure even if another module toggled Flask config.
    app.config['DEBUG'] = False
    app.config['PROPAGATE_EXCEPTIONS'] = False
