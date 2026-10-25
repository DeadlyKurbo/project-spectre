from __future__ import annotations

from fastapi.testclient import TestClient

import config_app


def test_missing_tos_cookie_redirects_guarded_route():
    client = TestClient(config_app.app)

    response = client.get("/features", follow_redirects=False)

    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/?tos=required&next=%2Ffeatures"


def test_accept_tos_sets_one_year_cookie():
    client = TestClient(config_app.app)

    response = client.post("/tos/accept")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    set_cookie = response.headers.get("set-cookie", "")
    assert f"{config_app.TOS_CONSENT_COOKIE_NAME}={config_app.TOS_CONSENT_COOKIE_VALUE}" in set_cookie
    assert f"Max-Age={config_app.TOS_CONSENT_MAX_AGE_SECONDS}" in set_cookie


def test_guarded_route_allows_request_when_tos_cookie_present(monkeypatch):
    async def _anonymous_context(_request):
        return None, []

    monkeypatch.setattr(config_app, "_load_user_context", _anonymous_context)

    client = TestClient(config_app.app)
    client.cookies.set(config_app.TOS_CONSENT_COOKIE_NAME, config_app.TOS_CONSENT_COOKIE_VALUE)
    response = client.get("/features", follow_redirects=False)

    assert response.status_code == 200
    assert "Project Spectre" in response.text


def test_dashboard_no_tos_redirect_when_cookie_present():
    client = TestClient(config_app.app)
    client.cookies.set(config_app.TOS_CONSENT_COOKIE_NAME, config_app.TOS_CONSENT_COOKIE_VALUE)

    response = client.get("/dashboard", follow_redirects=False)

    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/login"
