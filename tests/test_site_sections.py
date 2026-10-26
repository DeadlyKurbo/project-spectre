import importlib
import json
import sys

import pytest
from fastapi.testclient import TestClient

import config
import site_sections


def test_paths_map_to_the_section_that_serves_them():
    lookup = lambda path: (site_sections.section_for_path(path) or site_sections.SiteSection("", "", "", ())).key
    assert lookup("/alice") == "alice"
    assert lookup("/api/alice/command") == "alice"
    # The old chat URLs belong to ZETA, not A.L.I.C.E.
    assert lookup("/alice/chat") == "zeta"
    assert lookup("/api/alice/chat/123") == "zeta"
    assert lookup("/zeta/join") == "zeta"
    assert lookup("/wasp") == "wasp"
    assert lookup("/wasp/archive") == "wasp_archive"
    assert lookup("/api/wasp/archive/browse") == "wasp_archive"
    assert lookup("/wasp-map") == "wasp_map"
    assert lookup("/server/123") == "dashboard"
    # Whole segments only, and never the landing page or the consoles.
    assert lookup("/aliceband") == ""
    for path in ("/", "/admin", "/admin/sections", "/director", "/login", "/static/spectre.css", "/media/wasp/a.mp3"):
        assert lookup(path) == "", path


def test_section_lock_roundtrip(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_FILE", str(cfg))
    assert config.get_section_lock_states() == {}

    config.set_section_lock_state("alice", "maintenance", actor="Ada (42)", message="  Patching  ")
    first = config.get_section_lock_states()["alice"]
    assert first["mode"] == "maintenance"
    assert first["message"] == "Patching"
    assert first["actor"] == "Ada (42)"
    assert first["enabled_at"]

    # Escalating to disabled keeps the original start time.
    config.set_section_lock_state("alice", "disabled", actor="Ada (42)")
    second = config.get_section_lock_states()["alice"]
    assert second["mode"] == "disabled" and second["message"] == ""
    assert second["enabled_at"] == first["enabled_at"]

    config.set_section_lock_state("alice", "online")
    assert config.get_section_lock_states() == {}
    assert json.loads(cfg.read_text())["section_locks"] == {}

    with pytest.raises(ValueError):
        config.set_section_lock_state("alice", "sideways")


def test_section_locks_leave_the_site_lockdown_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", str(tmp_path / "config.json"))
    config.set_site_lock_state(True, actor="Ada", message="Moving servers")
    config.set_section_lock_state("zeta", "disabled")
    assert config.get_site_lock_state()["enabled"] is True
    config.set_site_lock_state(False)
    assert config.get_section_lock_states()["zeta"]["mode"] == "disabled"


def _load_app(monkeypatch, locks, *, admin=False):
    monkeypatch.setenv("DASHBOARD_USERNAME", "user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass")
    sys.modules.pop("config_app", None)
    mod = importlib.import_module("config_app")
    monkeypatch.setattr(mod, "record_website_user", lambda _user: None)
    monkeypatch.setattr(
        mod,
        "get_site_lock_state",
        lambda: {"enabled": False, "message": mod.SITE_LOCK_MESSAGE_DEFAULT, "actor": None, "enabled_at": None},
    )
    monkeypatch.setattr(mod, "get_section_lock_states", lambda: locks)
    monkeypatch.setattr(mod, "_session_user_is_admin", lambda _request: admin)

    async def no_user(_request):
        return None, []

    monkeypatch.setattr(mod, "_load_user_context", no_user)
    client = TestClient(mod.app)
    client.cookies.set(mod.TOS_CONSENT_COOKIE_NAME, mod.TOS_CONSENT_COOKIE_VALUE)
    return mod, client


def _lock(mode, message=""):
    return {"mode": mode, "message": message, "actor": "Ada (42)", "enabled_at": "2026-10-26T12:00:00+00:00", "updated_at": None}


def test_section_in_maintenance_shows_visitors_its_notice(monkeypatch):
    _mod, client = _load_app(monkeypatch, {"about": _lock("maintenance", "Rewriting the history page")})
    resp = client.get("/about", headers={"Accept": "text/html"})
    assert resp.status_code == 503
    assert "About is under maintenance" in resp.text
    assert "Rewriting the history page" in resp.text
    assert "Ada" in resp.text and "(42)" not in resp.text

    # fetch() callers get JSON instead of a page.
    fetched = client.get("/about", headers={"Accept": "*/*"})
    assert fetched.status_code == 503 and fetched.json()["mode"] == "maintenance"


def test_api_calls_in_a_locked_section_get_json(monkeypatch):
    _mod, client = _load_app(monkeypatch, {"alice": _lock("disabled", "Security review")})
    resp = client.post("/api/alice/command", json={"command": "help"})
    assert resp.status_code == 503
    assert resp.json() == {
        "detail": "A.L.I.C.E. is offline.",
        "section": "alice",
        "mode": "disabled",
        "message": "Security review",
    }
    page = client.get("/alice", headers={"Accept": "text/html"}, follow_redirects=False)
    assert page.status_code == 503 and "A.L.I.C.E. is offline" in page.text


def test_maintenance_lets_admins_in_but_disabled_does_not(monkeypatch):
    _mod, client = _load_app(monkeypatch, {"about": _lock("maintenance")}, admin=True)
    assert client.get("/about").status_code == 200

    _mod, client = _load_app(monkeypatch, {"about": _lock("disabled")}, admin=True)
    assert client.get("/about").status_code == 503


def test_other_sections_and_the_landing_page_stay_open(monkeypatch):
    mod, client = _load_app(monkeypatch, {"alice": _lock("disabled")})

    async def fake_facts(_user, _request):
        return "<div>facts</div>"

    monkeypatch.setattr(mod, "_render_bot_facts_block", fake_facts)
    assert client.get("/about").status_code == 200
    assert client.get("/").status_code == 200


@pytest.fixture
def admin_client(monkeypatch):
    mod, client = _load_app(monkeypatch, {"zeta": _lock("maintenance", "Moving chat storage")}, admin=True)

    async def admin_user(_request):
        return {"id": "42", "username": "Ada", "discriminator": "0"}, []

    monkeypatch.setattr(mod, "_load_user_context", admin_user)
    settings = mod.OwnerSettings(
        bot_version="v2.4",
        latest_update="",
        managers=["42"],
        fleet_managers=[],
        chat_access=[],
        bot_active=True,
        moderation=mod.ModerationSettings(),
        change_log=[],
    )
    monkeypatch.setattr(mod, "load_owner_settings", lambda **_kw: (settings, "etag"))
    return mod, client


def test_admin_section_form_saves_the_chosen_state(admin_client, monkeypatch):
    mod, client = admin_client
    calls = []
    monkeypatch.setattr(mod, "set_section_lock_state", lambda key, mode, **kw: calls.append((key, mode, kw)))

    resp = client.post(
        "/admin/sections",
        data={"section": "alice", "mode": "disabled", "message": "Security review"},
        follow_redirects=False,
    )
    assert resp.status_code == 303 and resp.headers["location"] == "/admin#sections"
    assert calls == [("alice", "disabled", {"actor": "Ada (42)", "message": "Security review"})]

    client.post("/admin/sections", data={"section": "nowhere", "mode": "disabled"}, follow_redirects=False)
    client.post("/admin/sections", data={"section": "alice", "mode": "sideways"}, follow_redirects=False)
    assert len(calls) == 1


def test_admin_section_preview_uses_the_draft(admin_client):
    _mod, client = admin_client
    resp = client.post("/admin/sections/preview", data={"section": "alice", "mode": "disabled", "message": "Back Friday"})
    assert resp.status_code == 200
    assert "Preview" in resp.text and "A.L.I.C.E. is offline" in resp.text and "Back Friday" in resp.text


def test_admin_section_routes_are_admin_only(monkeypatch):
    mod, client = _load_app(monkeypatch, {})

    async def stranger(_request):
        return {"id": "99", "username": "Nobody"}, []

    monkeypatch.setattr(mod, "_load_user_context", stranger)
    calls = []
    monkeypatch.setattr(mod, "set_section_lock_state", lambda *a, **kw: calls.append(a))
    resp = client.post("/admin/sections", data={"section": "alice", "mode": "disabled"}, follow_redirects=False)
    assert resp.status_code in {302, 303, 401, 403}
    assert calls == []
