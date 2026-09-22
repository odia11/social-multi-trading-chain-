"""Fail-closed CSRF enforcement for authenticated legacy mutation routes.

Some older OrcAgent handlers are decorated csrf_exempt because they predate the
current browser CSRF plumbing.  Their callers now have a session token, so those
exemptions must not weaken authenticated state changes or money movement.

This layer intentionally does not touch login/session-bootstrap endpoints.  It
only covers authenticated routes whose route-level decorator would otherwise
skip dashboard._csrf_check().
"""
from __future__ import annotations

import re
from flask import jsonify, request

_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_EXACT = frozenset({
    "/api/instant-trade",
    "/api/copy-trade/toggle",
    "/api/push/subscribe",
    "/api/push/unsubscribe",
    "/api/settings/save",
    "/api/settings/trading-profile",
    "/api/follow/toggle",
    "/api/invite/respond",
})
_POST_MUTATION = re.compile(r"^/api/post/\d+/(?:edit|delete)$")


def _protected(path: str) -> bool:
    # Admin GETs are skipped by the method gate; every admin mutation must
    # carry the same per-session CSRF token as ordinary user mutations.
    return (
        path in _EXACT
        or bool(_POST_MUTATION.fullmatch(path))
        or path.startswith("/api/admin/")
    )


def install(dashboard_module) -> None:
    app = dashboard_module.app
    if getattr(app, "_orca_authenticated_csrf_hardening_installed", False):
        return
    app._orca_authenticated_csrf_hardening_installed = True

    validate = getattr(dashboard_module, "_validate_csrf", None)
    auth = getattr(dashboard_module, "_authenticated_wallet", None)
    if not callable(validate) or not callable(auth):
        raise RuntimeError("Authenticated CSRF hardening requires dashboard auth + CSRF helpers")

    @app.before_request
    def _authenticated_legacy_csrf_guard():
        if request.method.upper() not in _MUTATING:
            return None
        path = request.path or ""
        if not _protected(path):
            return None

        try:
            wallet = auth()
        except Exception:
            wallet = None
        # The route itself still owns the normal 401 response.  CSRF is a
        # session-bound invariant and therefore applies once a wallet session
        # has actually been authenticated.
        if not wallet:
            return None

        token = (
            request.headers.get("X-CSRF-Token")
            or request.headers.get("X-CSRFToken")
            or ""
        )
        if not token and request.is_json:
            body = request.get_json(silent=True)
            if isinstance(body, dict):
                token = str(body.get("csrf_token") or "")

        try:
            ok = bool(validate(str(token or "")))
        except Exception:
            ok = False
        if not ok:
            app.logger.warning("authenticated CSRF blocked path=%s", path)
            return jsonify({"ok": False, "error": "CSRF validation failed"}), 403
        return None
