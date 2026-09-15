"""Mandatory CSRF validation for every browser-facing admin mutation.

Several legacy admin handlers are decorated csrf_exempt even though the current
admin UI already sends X-CSRF-Token. SameSite/Origin checks are useful defense in
depth, but a privileged mutation should also require the per-session secret.
This outer guard makes that invariant independent of individual route decorators.
"""
from __future__ import annotations

from flask import jsonify, request

_MUTATING = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_admin_csrf_hardening_installed', False):
        return
    app._orca_admin_csrf_hardening_installed = True

    validate = getattr(dashboard_module, '_validate_csrf', None)
    if not callable(validate):
        raise RuntimeError('Admin CSRF hardening requires dashboard._validate_csrf')

    @app.before_request
    def _require_admin_csrf():
        path = request.path or ''
        if request.method.upper() not in _MUTATING or not (
            path == '/api/admin' or path.startswith('/api/admin/')
        ):
            return None

        token = (
            request.headers.get('X-CSRF-Token')
            or request.headers.get('X-CSRFToken')
            or ''
        )
        try:
            ok = bool(validate(token))
        except Exception:
            ok = False
        if not ok:
            app.logger.warning('admin CSRF validation failed path=%s', path)
            return jsonify({'ok': False, 'error': 'CSRF validation failed'}), 403
        return None
