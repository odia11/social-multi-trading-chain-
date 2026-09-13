"""Lightweight security anomaly monitoring.

This does not page an external service by itself; it emits structured WARNING lines to
journalctl when one client repeatedly hits auth/authorization/rate-limit failures or
when sensitive money/admin actions fail unusually often. Those lines are suitable for
systemd/journald alert collectors and preserve no raw request bodies or secrets.
"""
from __future__ import annotations

import collections
import hashlib
import os
import threading
import time

from flask import request

_LOCK = threading.Lock()
_EVENTS = collections.defaultdict(collections.deque)
_WINDOW = 300
_THRESHOLDS = {401: 12, 403: 12, 429: 8}
_SENSITIVE = ('/api/admin', '/api/withdraw', '/api/bridge', '/api/trade', '/api/wallet/set', '/api/session/')


def _client_key() -> str:
    ip = (request.headers.get('X-Forwarded-For') or '').split(',')[0].strip() or request.remote_addr or ''
    salt = str(os.getenv('SECRET_KEY') or 'monitor').encode()
    return hashlib.sha256(salt + b'|' + ip.encode()).hexdigest()[:16]


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_security_monitoring_installed', False):
        return
    app._orca_security_monitoring_installed = True

    @app.after_request
    def _monitor(response):
        path = request.path or ''
        status = int(response.status_code)
        now = time.time()
        if status not in _THRESHOLDS and not (status >= 500 and any(path.startswith(p) for p in _SENSITIVE)):
            return response
        client = _client_key()
        bucket_key = (client, status, path.split('?', 1)[0][:120])
        with _LOCK:
            dq = _EVENTS[bucket_key]
            dq.append(now)
            cutoff = now - _WINDOW
            while dq and dq[0] < cutoff:
                dq.popleft()
            count = len(dq)
            # Bound memory: remove stale buckets opportunistically.
            if len(_EVENTS) > 5000:
                for key in list(_EVENTS)[:1000]:
                    q = _EVENTS[key]
                    while q and q[0] < cutoff:
                        q.popleft()
                    if not q:
                        _EVENTS.pop(key, None)
        threshold = _THRESHOLDS.get(status, 3)
        if count == threshold or (count > threshold and count % threshold == 0):
            app.logger.warning(
                'SECURITY_ANOMALY client=%s status=%s path=%s count=%s window=%ss',
                client, status, path[:160], count, _WINDOW,
            )
        return response
