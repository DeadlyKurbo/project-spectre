import importlib
import sys

from fastapi.testclient import TestClient


def _load_app(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass")
    sys.modules.pop("config_app", None)
    return importlib.import_module("config_app")


def _as_director(monkeypatch, mod):
    async def fake_require_director(_request):
        return {"id": "99", "username": "Nova", "discriminator": "0"}, None

    monkeypatch.setattr(mod, "_require_director", fake_require_director)


def _fake_bot_state(monkeypatch, mod, *, desired="running", state="online"):
    monkeypatch.setattr(
        mod,
        "get_bot_control",
        lambda: {
            "desired": desired,
            "restart_requested_at": None,
            "actor": "Nova (99)" if desired == "stopped" else None,
            "reason": "Hotfix" if desired == "stopped" else None,
            "updated_at": "2026-10-24T07:00:00+00:00",
        },
    )
    monkeypatch.setattr(
        mod,
        "get_bot_status",
        lambda: {
            "state": state,
            "heartbeat_at": "2026-10-24T07:01:00+00:00",
            "session_started_at": "2026-10-24T06:00:00+00:00",
            "latency_ms": 48,
            "guild_count": 7,
            "bot_user": "Spectre#0001",
        },
    )


def test_director_bot_control_form_records_request(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)
    _as_director(monkeypatch, mod)
    calls = []
    monkeypatch.setattr(
        mod,
        "set_bot_control",
        lambda action, *, actor=None, reason=None: calls.append((action, actor, reason)),
    )

    resp = client.post(
        "/director/website-management",
        data={"action": "bot_control", "bot_action": "stop", "bot_reason": "Hotfix"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/director/website-management#bot-controls"
    assert calls == [("stop", "Nova (99)", "Hotfix")]

    resp = client.post(
        "/director/website-management",
        data={"action": "bot_control", "bot_action": "self-destruct"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert len(calls) == 1


def test_director_bot_status_endpoint(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)
    _as_director(monkeypatch, mod)
    _fake_bot_state(monkeypatch, mod, desired="stopped", state="online")

    resp = client.get("/director/bot/status")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["label"] == "Shutting down"
    assert payload["desired"] == "stopped"
    assert payload["guild_count"] == 7


def test_director_bot_status_handles_storage_errors(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)
    _as_director(monkeypatch, mod)

    def broken():
        raise RuntimeError("storage offline")

    monkeypatch.setattr(mod, "get_bot_control", broken)

    resp = client.get("/director/bot/status")
    assert resp.status_code == 200
    assert resp.json()["label"] == "Unavailable"


def test_website_management_collapses_music_and_shows_bot_panel(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)
    _as_director(monkeypatch, mod)
    _fake_bot_state(monkeypatch, mod)
    settings = mod.OwnerSettings(
        bot_version="v1",
        latest_update="msg",
        managers=[],
        fleet_managers=[],
        chat_access=[],
        bot_active=True,
        moderation=mod.ModerationSettings(),
        change_log=[],
    )
    monkeypatch.setattr(mod, "load_owner_settings", lambda **_kw: (settings, "etag"))
    tracks = [
        {
            "filename": f"track-{i}.mp3",
            "url": f"/media/wasp/track-{i}.mp3",
            "download_url": f"/media/wasp/track-{i}.mp3?download=1",
            "size": "1234",
            "updated_at": "2026-10-24T00:00:00+00:00",
        }
        for i in range(3)
    ]
    monkeypatch.setattr(mod, "_list_uploaded_wasp_tracks", lambda newest_first=False: tracks)

    resp = client.get("/director/website-management")
    assert resp.status_code == 200
    body = resp.text
    assert body.count('<details class="collapsible">') == 2
    assert "<details class=\"collapsible\" open" not in body
    assert "Uploaded Tracks" in body and "Custom Playback Order" in body
    assert 'id="bot-controls"' in body
    assert "Shut Down Bot" in body and "Restart Bot" in body
    assert "Spectre#0001" in body
