"""Injection hardening for dynamic identifiers used by legacy helpers.

SQL values in OrcAgent are parameterized.  A small number of helpers also use
server-selected SQL identifiers.  Keep those identifiers allowlisted at the
shared boundary so a future caller cannot accidentally turn them into an SQL
injection primitive.
"""
from __future__ import annotations

from flask import jsonify

_GROUP_IMAGE_FIELDS = frozenset({"avatar_url", "banner_url"})


def install(dashboard_module) -> None:
    app = dashboard_module.app
    if getattr(app, "_orca_injection_hardening_installed", False):
        return
    app._orca_injection_hardening_installed = True

    original = getattr(dashboard_module, "_group_image_upload", None)
    if callable(original) and not getattr(original, "_orca_identifier_guard", False):
        def guarded_group_image_upload(group_id, field, data):
            if field not in _GROUP_IMAGE_FIELDS:
                app.logger.warning("blocked unsafe group image SQL identifier=%r", field)
                return jsonify({"ok": False, "error": "Invalid image field"}), 400
            return original(group_id, field, data)

        guarded_group_image_upload._orca_identifier_guard = True
        guarded_group_image_upload._orca_original = original
        dashboard_module._group_image_upload = guarded_group_image_upload
