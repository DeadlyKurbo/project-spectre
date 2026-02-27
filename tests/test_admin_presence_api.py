from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import config_app


def test_admin_heartbeat_requires_id(monkeypatch):
    monkeypatch.setattr(config_app, "_load_user_context", _fake_user_context("42"))
    client = TestClient(config_app.app)

    response = client.post("/api/admin/heartbeat", json={"name": "Ada"})

    assert response.status_code == 400
    assert response.json() == {"error": "Missing admin ID"}


def test_admin_heartbeat_records_presence(monkeypatch):
    monkeypatch.setattr(config_app, "_load_user_context", _fake_user_context("42"))
    with config_app._ADMIN_PRESENCE_LOCK:
        config_app._ADMIN_PRESENCE.clear()

    client = TestClient(config_app.app)

    response = client.post(
        "/api/admin/heartbeat",
        json={"id": "42", "name": "Ada", "role": "Director", "clearance": "Omega-9"},
    )

    assert response.status_code == 200
    assert response.json() == {"success": True}

    roster = client.get("/api/admins")
    assert roster.status_code == 200
    payload = roster.json()
    assert payload == [
        {
            "id": "42",
            "name": "Ada",
            "role": "Director",
            "clearance": "Omega-9",
            "ip": "testclient",
            "status": "Online",
            "lastActive": "Just now",
        }
    ]


def test_admins_marks_stale_entries_offline():
    stale_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    with config_app._ADMIN_PRESENCE_LOCK:
        config_app._ADMIN_PRESENCE.clear()
        config_app._ADMIN_PRESENCE["9"] = {
            "id": "9",
            "name": "Morgan",
            "role": "Operator",
            "clearance": "Delta",
            "last_active": stale_at,
        }

    client = TestClient(config_app.app)
    response = client.get("/api/admins")

    assert response.status_code == 200
    assert response.json()[0]["status"] == "Offline"


def _fake_user_context(user_id: str):
    async def _loader(_request):
        return {"id": user_id, "username": "operator"}, []

    return _loader


def test_activity_feed_tracks_heartbeat(monkeypatch):
    monkeypatch.setattr(config_app, "_load_user_context", _fake_user_context("42"))
    with config_app._ACTIVITY_LOG_LOCK:
        config_app._ACTIVITY_LOGS.clear()

    client = TestClient(config_app.app)
    response = client.post(
        "/api/admin/heartbeat",
        json={"id": "42", "name": "Ada", "role": "Director", "clearance": "Omega-9"},
    )

    assert response.status_code == 200

    activity = client.get("/api/activity")
    assert activity.status_code == 200
    payload = activity.json()
    assert payload
    assert payload[0]["type"] == "heartbeat"
    assert payload[0]["user"] == "Ada"
    assert payload[0]["ip"] == "testclient"
    assert payload[0]["time"].endswith("+00:00")


def test_admin_team_records_login_activity(monkeypatch):
    monkeypatch.setattr(config_app, "_load_user_context", _fake_user_context("42"))

    owner_settings, _owner_etag = config_app.load_owner_settings()
    owner_settings = owner_settings.copy()
    owner_settings.managers = ["42"]

    def _fake_owner_settings():
        return owner_settings, "etag"

    monkeypatch.setattr(config_app, "load_owner_settings", _fake_owner_settings)
    monkeypatch.setattr(config_app, "load_admin_bios", lambda: {})

    async def _fake_roster(*_args, **_kwargs):
        return []

    monkeypatch.setattr(config_app, "_build_admin_roster_entries", _fake_roster)

    with config_app._ACTIVITY_LOG_LOCK:
        config_app._ACTIVITY_LOGS.clear()

    client = TestClient(config_app.app)
    response = client.get("/admin-team")

    assert response.status_code == 200

    activity = client.get("/api/activity")
    payload = activity.json()
    assert payload
    assert payload[0]["type"] == "login"
    assert payload[0]["user"] == "operator"
    assert payload[0]["ip"] == "testclient"
