from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import config_app


def _auth_headers(client: TestClient) -> dict[str, str]:
    token_response = client.get("/api/auth/token")
    assert token_response.status_code == 200
    token = token_response.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_admin_heartbeat_requires_id(monkeypatch):
    monkeypatch.setattr(config_app, "_load_user_context", _fake_user_context("42"))
    client = TestClient(config_app.app)

    response = client.post("/api/admin/heartbeat", json={"name": "Ada"}, headers=_auth_headers(client))

    assert response.status_code == 400
    assert response.json() == {"error": "Missing admin ID"}


def test_admin_heartbeat_records_presence(monkeypatch):
    monkeypatch.setattr(config_app, "_load_user_context", _fake_user_context("42"))
    with config_app._ADMIN_PRESENCE_LOCK:
        config_app._ADMIN_PRESENCE.clear()
        config_app._ADMIN_PRESENCE_LOADED = True

    client = TestClient(config_app.app)
    headers = _auth_headers(client)

    response = client.post(
        "/api/admin/heartbeat",
        json={"id": "42", "name": "Ada", "role": "Director", "clearance": "Omega-9"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == {"success": True}

    roster = client.get("/api/admins", headers=headers)
    assert roster.status_code == 200
    payload = roster.json()
    assert payload == [
        {
            "id": "42",
            "name": "Ada",
            "role": "Director",
            "clearance": "Omega-9",
            "status": "Online",
            "lastActive": "Recently",
        }
    ]


def test_director_admins_includes_ip(monkeypatch):
    monkeypatch.setattr(config_app, "_load_user_context", _fake_user_context("1059522006602752150"))
    with config_app._ADMIN_PRESENCE_LOCK:
        config_app._ADMIN_PRESENCE.clear()
        config_app._ADMIN_PRESENCE_LOADED = True

    client = TestClient(config_app.app)
    headers = _auth_headers(client)

    client.post(
        "/api/admin/heartbeat",
        json={"id": "1059522006602752150", "name": "Ada", "role": "Director", "clearance": "Omega-9"},
        headers=headers,
    )

    roster = client.get("/api/director/admins", headers=headers)
    assert roster.status_code == 200
    assert roster.json()[0]["ip"] == "testclient"


def test_admins_marks_stale_entries_offline():
    stale_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    with config_app._ADMIN_PRESENCE_LOCK:
        config_app._ADMIN_PRESENCE.clear()
        config_app._ADMIN_PRESENCE_LOADED = True
        config_app._ADMIN_PRESENCE["9"] = {
            "id": "9",
            "name": "Morgan",
            "role": "Operator",
            "clearance": "Delta",
            "last_active": stale_at,
        }

    client = TestClient(config_app.app)
    # seed authenticated context
    config_app._load_user_context = _fake_user_context("42")
    response = client.get("/api/admins", headers=_auth_headers(client))

    assert response.status_code == 200
    assert response.json()[0]["status"] == "Offline"


def test_format_time_ago_supports_longer_ranges():
    assert config_app._format_time_ago(timedelta(seconds=30)) == "Recently"
    assert config_app._format_time_ago(timedelta(minutes=5)) == "5 minutes ago"
    assert config_app._format_time_ago(timedelta(hours=2)) == "2 hours ago"
    assert config_app._format_time_ago(timedelta(days=4)) == "4 days ago"
    assert config_app._format_time_ago(timedelta(days=21)) == "3 weeks ago"
    assert config_app._format_time_ago(timedelta(days=65)) == "2 months ago"


def _fake_user_context(user_id: str):
    async def _loader(_request):
        return {"id": user_id, "username": "operator"}, []

    return _loader


def test_activity_feed_tracks_heartbeat(monkeypatch):
    monkeypatch.setattr(config_app, "_load_user_context", _fake_user_context("1059522006602752150"))
    with config_app._ACTIVITY_LOG_LOCK:
        config_app._ACTIVITY_LOGS.clear()

    client = TestClient(config_app.app)
    headers = _auth_headers(client)
    response = client.post(
        "/api/admin/heartbeat",
        json={"id": "1059522006602752150", "name": "Ada", "role": "Director", "clearance": "Omega-9"},
        headers=headers,
    )

    assert response.status_code == 200

    activity = client.get("/api/activity", headers=headers)
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

    # Managers are not directors, so activity API should be restricted.
    activity = client.get("/api/activity", headers=_auth_headers(client))
    assert activity.status_code == 403


def test_director_security_overview_renders_admin_and_ip_data(monkeypatch):
    monkeypatch.setattr(config_app, "_load_user_context", _fake_user_context("1059522006602752150"))
    with config_app._ADMIN_PRESENCE_LOCK:
        config_app._ADMIN_PRESENCE.clear()
        config_app._ADMIN_PRESENCE_LOADED = True
    with config_app._ACTIVITY_LOG_LOCK:
        config_app._ACTIVITY_LOGS.clear()

    config_app._record_admin_heartbeat(
        "1059522006602752150",
        name="Ada",
        role="Director",
        clearance="Omega-9",
        ip="203.0.113.8",
    )
    config_app._log_activity("heartbeat", "Ada", "203.0.113.8")

    async def fake_require_director(_request):
        return {"id": "1059522006602752150", "username": "Ada"}, None

    monkeypatch.setattr(config_app, "_require_director", fake_require_director)

    client = TestClient(config_app.app)
    response = client.get("/director/security-overview")

    assert response.status_code == 200
    body = response.text
    assert "Security. <span>Overview.</span>" in body
    assert "Admin Presence (with IP)" in body
    assert "203.0.113.8" in body




def test_monthly_site_visits_counts_last_30_days_only():
    now = datetime.now(timezone.utc).date()
    with config_app._SITE_VISIT_LOG_LOCK:
        config_app._SITE_VISIT_DAILY.clear()
        config_app._SITE_VISIT_LOADED = True
        config_app._SITE_VISIT_DAILY[(now - timedelta(days=5)).isoformat()] = 12
        config_app._SITE_VISIT_DAILY[(now - timedelta(days=29)).isoformat()] = 8
        config_app._SITE_VISIT_DAILY[(now - timedelta(days=31)).isoformat()] = 20

    assert config_app._monthly_site_visits() == 20


def test_director_security_overview_has_monthly_visits_and_reveal_ip(monkeypatch):
    monkeypatch.setattr(config_app, "_load_user_context", _fake_user_context("1059522006602752150"))
    with config_app._ADMIN_PRESENCE_LOCK:
        config_app._ADMIN_PRESENCE.clear()
        config_app._ADMIN_PRESENCE_LOADED = True
    with config_app._ACTIVITY_LOG_LOCK:
        config_app._ACTIVITY_LOGS.clear()

    config_app._record_admin_heartbeat(
        "1059522006602752150",
        name="Ada",
        role="Director",
        clearance="Omega-9",
        ip="203.0.113.8",
    )
    config_app._log_activity("heartbeat", "Ada", "203.0.113.8")

    with config_app._SITE_VISIT_LOG_LOCK:
        config_app._SITE_VISIT_DAILY.clear()
        config_app._SITE_VISIT_LOADED = True
        config_app._SITE_VISIT_DAILY[datetime.now(timezone.utc).date().isoformat()] = 34

    async def fake_require_director(_request):
        return {"id": "1059522006602752150", "username": "Ada"}, None

    monkeypatch.setattr(config_app, "_require_director", fake_require_director)

    client = TestClient(config_app.app)
    response = client.get("/director/security-overview")

    assert response.status_code == 200
    body = response.text
    assert "Website Visits (30D)" in body
    assert "Reveal IP" in body

def test_admin_team_uses_manual_rank_labels(monkeypatch):
    monkeypatch.setattr(config_app, "_load_user_context", _fake_user_context("42"))

    owner_settings, _owner_etag = config_app.load_owner_settings()
    owner_settings = owner_settings.copy()
    owner_settings.managers = ["42"]

    monkeypatch.setattr(config_app, "load_owner_settings", lambda: (owner_settings, "etag"))
    monkeypatch.setattr(config_app, "load_admin_bios", lambda: {})
    monkeypatch.setattr(
        config_app,
        "load_admin_team_settings",
        lambda: config_app.AdminTeamSettings(members=["42"], ranks={"42": "Operations Chief"}, clearances={}),
    )

    async def _fake_roster(_admin_ids, _bios, _current_user_id, _ranks=None, _clearances=None):
        return [
            {
                "id": "42",
                "name": "Ada",
                "username": "ada",
                "role": "Operations Chief",
                "avatar": None,
                "initials": "A",
                "bio": "",
                "profile_url": "https://discord.com/users/42",
                "can_edit": True,
                "has_bio": False,
                "clearance": "Omega-9",
            }
        ]

    monkeypatch.setattr(config_app, "_build_admin_roster_entries", _fake_roster)

    client = TestClient(config_app.app)
    response = client.get("/admin-team")

    assert response.status_code == 200
    assert "Operations Chief" in response.text


def test_director_personnel_updates_team_settings(monkeypatch):
    monkeypatch.setattr(config_app, "_load_user_context", _fake_user_context("1059522006602752150"))

    async def fake_require_director(_request):
        return {"id": "1059522006602752150", "username": "Owner"}, None

    monkeypatch.setattr(config_app, "_require_director", fake_require_director)
    monkeypatch.setattr(config_app, "load_admin_bios", lambda: {})
    monkeypatch.setattr(
        config_app,
        "load_admin_team_settings",
        lambda: config_app.AdminTeamSettings(members=["42"], ranks={"42": "System Overseer"}, clearances={}),
    )

    owner_settings, _owner_etag = config_app.load_owner_settings()
    owner_settings = owner_settings.copy()
    monkeypatch.setattr(config_app, "load_owner_settings", lambda: (owner_settings, "etag"))

    async def _fake_roster(_admin_ids, _bios, _current_user_id, _ranks=None, _clearances=None):
        return []

    monkeypatch.setattr(config_app, "_build_admin_roster_entries", _fake_roster)

    captured = {}

    def fake_save(settings):
        captured["members"] = settings.members
        captured["ranks"] = settings.ranks
        captured["clearances"] = settings.clearances
        return settings

    monkeypatch.setattr(config_app, "save_admin_team_settings", fake_save)

    client = TestClient(config_app.app)
    response = client.post(
        "/director/personnel",
        data={
            "member_ids": "42\n84\ninvalid",
            "rank_42": "Lead Overseer",
            "rank_84": "Night Watch",
            "clearance_42": "Sigma-2",
            "clearance_84": "Kappa-4",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/director/personnel"
    assert captured == {
        "members": ["42", "84"],
        "ranks": {"42": "Lead Overseer", "84": "Night Watch"},
        "clearances": {"42": "Sigma-2", "84": "Kappa-4"},
    }
