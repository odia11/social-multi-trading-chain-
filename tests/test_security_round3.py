"""Regression tests for the October 2026 security hardening round."""
from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify

import authenticated_csrf_hardening
import response_privacy_hardening


def test_admin_mutation_csrf_exemption_is_removed_at_install():
    app = Flask(__name__)
    app.secret_key = "security-test-only"

    def mutate():
        return "ok", 200

    mutate._csrf_exempt = True
    app.add_url_rule(
        "/api/admin/change",
        "admin_change",
        mutate,
        methods=["POST"],
    )
    d = SimpleNamespace(
        app=app,
        _authenticated_wallet=lambda: "wallet-one",
        _validate_csrf=lambda token: token == "good-token",
    )
    authenticated_csrf_hardening.install(d)

    assert getattr(app.view_functions["admin_change"], "_csrf_exempt", False) is False

    client = app.test_client()
    assert client.post("/api/admin/change", json={}).status_code == 403
    assert client.post(
        "/api/admin/change",
        json={},
        headers={"X-CSRF-Token": "good-token"},
    ).status_code == 200


def test_api_5xx_never_leaks_internal_error_details():
    app = Flask(__name__)
    app.secret_key = "security-test-only"

    @app.get("/api/fail")
    def fail():
        return jsonify({
            "ok": False,
            "error": "sqlite3.OperationalError: no such table secret_internal",
            "detail": "/data/orcagent.db provider_token=do-not-leak",
            "retryable": True,
        }), 500

    response_privacy_hardening.install(SimpleNamespace(app=app))
    response = app.test_client().get("/api/fail")
    body = response.get_data(as_text=True)

    assert response.status_code == 500
    assert response.headers.get("Cache-Control") == "no-store"
    assert "secret_internal" not in body
    assert "/data/orcagent.db" not in body
    assert "provider_token" not in body
    assert response.get_json() == {
        "ok": False,
        "retryable": True,
        "error": "Something went wrong on our side",
    }


if __name__ == "__main__":
    test_admin_mutation_csrf_exemption_is_removed_at_install()
    print("PASS test_admin_mutation_csrf_exemption_is_removed_at_install")
    test_api_5xx_never_leaks_internal_error_details()
    print("PASS test_api_5xx_never_leaks_internal_error_details")
    print("ALL SECURITY ROUND 3 REGRESSIONS PASSED")
