from __future__ import annotations

from fastapi.testclient import TestClient

import config_app


def test_issue_api_token_uses_session_user(monkeypatch):
    monkeypatch.setattr(
        config_app,
        "_session_user_for_api_token",
        lambda _request: {"id": "42", "username": "operator", "global_name": "Operator"},
    )
    client = TestClient(config_app.app)

    response = client.get("/api/auth/token")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload.get("token"), str)
    assert payload.get("expiresIn", 0) > 0


def test_issue_api_token_requires_session_user(monkeypatch):
    monkeypatch.setattr(config_app, "_session_user_for_api_token", lambda _request: None)
    client = TestClient(config_app.app)

    response = client.get("/api/auth/token")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"
