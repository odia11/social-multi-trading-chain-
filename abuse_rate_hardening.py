"""Coarse per-action abuse ceilings above the app's route-specific limits.

Existing endpoint decorators remain the primary rate limits. These category limits are
a second wall so a newly added sensitive route cannot accidentally be unlimited.
"""
from __future__ import annotations

import hashlib

from flask import jsonify, request


def _ip_key():
    ip = (request.headers.get('X-Forwarded-For') or '').split(',')[0].strip() or request.remote_addr or ''
    return hashlib.sha256(ip.encode()).hexdigest()[:20]


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_abuse_rate_hardening_installed', False):
        return
    app._orca_abuse_rate_hardening_installed = True
    rate_ok = getattr(dashboard_module, '_rate_ok', None)
    if not callable(rate_ok):
        app.logger.warning('abuse rate hardening could not find _rate_ok')
        return

    @app.before_request
    def _abuse_ceiling():
        path = request.path or ''
        method = request.method.upper()
        if method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            return None

        auth_paths = ('/api/phantom/', '/api/wallet/set', '/api/session/resume', '/api/pair/')
        if path.startswith(auth_paths):
            key, limit, window = 'sec:auth:' + _ip_key(), 50, 300
        else:
            auth_fn = getattr(dashboard_module, '_authenticated_wallet', None)
            wallet = auth_fn() if callable(auth_fn) else None
            actor = str(wallet or _ip_key())
            if path.startswith('/api/withdraw') or path.startswith('/api/wallet/send'):
                key, limit, window = 'sec:withdraw:' + actor, 10, 3600
            elif path.startswith('/api/bridge/execute'):
                key, limit, window = 'sec:bridge:' + actor, 30, 3600
            elif path.startswith('/api/trade/') or path.startswith('/api/instant-trade'):
                key, limit, window = 'sec:trade:' + actor, 120, 60
            elif path.startswith('/api/admin/'):
                key, limit, window = 'sec:admin:' + actor, 120, 60
            elif path.startswith(('/api/messages', '/api/posts', '/api/groups', '/api/notifications')):
                key, limit, window = 'sec:social:' + actor, 180, 60
            else:
                return None
        if not rate_ok(key, limit, window):
            app.logger.warning('security rate ceiling hit category=%s path=%s', key.split(':', 2)[1], path)
            return jsonify({'ok': False, 'error': 'Too many requests'}), 429
        return None
