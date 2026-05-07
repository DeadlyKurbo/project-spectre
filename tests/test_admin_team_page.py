from __future__ import annotations

from fastapi.testclient import TestClient

import config_app


def test_admin_team_page_renders_for_public_viewer(monkeypatch):
    async def _anonymous_context(_request):
        return None, []

    monkeypatch.setattr(config_app, "_load_user_context", _anonymous_context)

    client = TestClient(config_app.app)
    response = client.get("/admin-team")

    assert response.status_code == 200
    assert "Admin team directory" in response.text
    assert "admin-card__msg-link" in response.text


def test_admin_team_page_stays_public_when_spa_enabled(monkeypatch):
    async def _anonymous_context(_request):
        return None, []

    monkeypatch.setattr(config_app, "_load_user_context", _anonymous_context)
    monkeypatch.setenv("ADMIN_MODERATION_SPA_ENABLED", "1")

    client = TestClient(config_app.app)
    response = client.get("/admin-team", follow_redirects=False)

    assert response.status_code == 200
    assert "Admin team directory" in response.text
