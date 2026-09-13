"""Authorization/IDOR hardening for privileged OrcAgent routes.

This is a fail-closed outer guard for the admin surface. Individual admin
handlers still keep their narrower _require_role/owner checks; this layer makes
sure a missed decorator or future endpoint cannot accidentally become public.
"""
from __future__ import annotations

import os
import sqlite3

from flask import jsonify, request

_ADMIN_ROLES = frozenset({'admin', 'executive', 'moderator', 'analyst'})


def _owner_wallets() -> set[str]:
    return {w.strip() for w in os.getenv('OWNER_WALLET', '').split(',') if w.strip()}


def _role_for_wallet(dashboard_module, wallet: str) -> str:
    if not wallet:
        return 'user'
    if wallet in _owner_wallets():
        return 'admin'
    db_file = getattr(dashboard_module, 'DB_FILE', None)
    if not db_file:
        return 'user'
    try:
        conn = sqlite3.connect(db_file)
        try:
            row = conn.execute(
                'SELECT role FROM users WHERE wallet_address=? LIMIT 1',
                (wallet,),
            ).fetchone()
            return str(row[0] or 'user').strip().lower() if row else 'user'
        finally:
            conn.close()
    except Exception:
        # Authorization must fail closed if role lookup is unavailable.
        return 'user'


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_authorization_hardening_installed', False):
        return
    app._orca_authorization_hardening_installed = True

    @app.before_request
    def _privileged_route_guard():
        path = request.path or '/'

        # All admin HTML/API routes require a cryptographically authenticated
        # wallet AND an explicit privileged DB role. A wallet string in a
        # read-only/unverified session is intentionally not enough.
        privileged = (
            path == '/admin' or path.startswith('/admin/') or
            path == '/api/admin' or path.startswith('/api/admin/') or
            path == '/bridge-test' or path.startswith('/bridge-test/')
        )
        if not privileged:
            return None

        auth_fn = getattr(dashboard_module, '_authenticated_wallet', None)
        wallet = auth_fn() if callable(auth_fn) else None
        if not wallet:
            if path.startswith('/api/'):
                return jsonify({'ok': False, 'error': 'Authentication required'}), 401
            return 'Authentication required', 401

        role = _role_for_wallet(dashboard_module, wallet)
        if role not in _ADMIN_ROLES:
            app.logger.warning(
                'authorization denied path=%s wallet=%s role=%s',
                path, str(wallet)[:8] + '…', role,
            )
            if path.startswith('/api/'):
                return jsonify({'ok': False, 'error': 'Forbidden'}), 403
            return 'Forbidden', 403

        return None
