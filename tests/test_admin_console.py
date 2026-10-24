import importlib
import sys

import pytest
from fastapi.testclient import TestClient


def _load_app(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass")
    sys.modules.pop("config_app", None)
    return importlib.import_module("config_app")


@pytest.fixture
def admin_client(monkeypatch):
    mod = _load_app(monkeypatch)
    settings = mod.OwnerSettings(
        bot_version="v2.4",
        latest_update="Archive search is back.",
        managers=["42"],
        fleet_managers=[],
        chat_access=[],
        bot_active=True,
        moderation=mod.ModerationSettings(),
        change_log=[],
    )

    async def fake_user(_request):
        return {"id": "42", "username": "Ada", "discriminator": "0"}, [{"id": "7", "name": "Section Zero"}]

    async def fake_facts(_user, _request):
        return '<div class="fact">facts</div>'

    async def fake_bot_guilds():
        return [{"id": "7", "name": "Section Zero"}]

    monkeypatch.setattr(mod, "_load_user_context", fake_user)
    monkeypatch.setattr(mod, "_render_bot_facts_block", fake_facts)
    monkeypatch.setattr(mod, "get_bot_guilds", fake_bot_guilds)
    monkeypatch.setattr(mod, "load_owner_settings", lambda **_kw: (settings, "etag"))
    monkeypatch.setattr(mod, "get_system_health_state", lambda: {"status": "degraded", "note": "Slow search"})
    monkeypatch.setattr(mod, "load_pyro_war_state", lambda: {"war_status": "active"})
    monkeypatch.setattr(
        mod,
        "get_site_lock_state",
        lambda: {"enabled": False, "message": mod.SITE_LOCK_MESSAGE_DEFAULT, "actor": None, "enabled_at": None},
    )
    client = TestClient(mod.app)
    client.cookies.set(mod.TOS_CONSENT_COOKIE_NAME, mod.TOS_CONSENT_COOKIE_VALUE)
    return mod, client


def test_admin_console_renders_every_section(admin_client):
    _mod, client = admin_client
    resp = client.get("/admin")
    assert resp.status_code == 200
    body = resp.text
    for section in ("overview", "people", "cases", "sanctions", "appeals", "audit", "site", "tools", "system"):
        assert f'id="{section}"' in body
    assert "Degraded" in body and "Slow search" in body
    assert "Archive search is back." in body
    assert '"discordServers": [{"id": "7", "name": "Section Zero"}]' in body
    assert "/static/admin/console.js" in body


def test_admin_console_is_admin_only(admin_client, monkeypatch):
    mod, client = admin_client

    async def stranger(_request):
        return {"id": "99", "username": "Nobody"}, []

    monkeypatch.setattr(mod, "_load_user_context", stranger)
    assert client.get("/admin").status_code == 403


def test_legacy_admin_url_redirects_to_console(admin_client):
    _mod, client = admin_client
    resp = client.get("/admin/legacy", follow_redirects=False)
    assert resp.status_code == 308
    assert resp.headers["location"] == "/admin"


def test_lockdown_form_saves_visitor_reason(admin_client, monkeypatch):
    mod, client = admin_client
    calls = []
    monkeypatch.setattr(mod, "set_site_lock_state", lambda enabled, **kw: calls.append(("set", enabled, kw)))
    monkeypatch.setattr(mod, "update_site_lock_message", lambda message: calls.append(("update", message)))

    resp = client.post("/admin/maintenance", data={"mode": "enable", "lock_message": "Database move"}, follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/admin#site"
    assert calls[-1] == ("set", True, {"actor": "Ada (42)", "message": "Database move"})

    client.post("/admin/maintenance", data={"mode": "update", "lock_message": "Nearly done"}, follow_redirects=False)
    assert calls[-1] == ("update", "Nearly done")
