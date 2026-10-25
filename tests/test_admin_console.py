import asyncio
import importlib
import sys

import pytest

import guild_blacklist
from app_spectre.services.moderation_service import InMemoryModerationRepository, ModerationService
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

    # The blacklist and moderation records live in memory instead of storage.
    blacklist_store: dict[str, dict] = {}

    def fake_read(key):
        if key not in blacklist_store:
            raise FileNotFoundError(key)
        return dict(blacklist_store[key])

    monkeypatch.setattr(guild_blacklist, "read_json", fake_read)
    monkeypatch.setattr(guild_blacklist, "save_json", lambda key, payload: blacklist_store.__setitem__(key, dict(payload)))
    service = ModerationService(InMemoryModerationRepository())
    monkeypatch.setattr(mod, "get_moderation_service", lambda: service)
    monkeypatch.setattr(mod, "moderation", service, raising=False)

    client = TestClient(mod.app)
    client.cookies.set(mod.TOS_CONSENT_COOKIE_NAME, mod.TOS_CONSENT_COOKIE_VALUE)
    return mod, client


def test_admin_console_renders_every_section(admin_client):
    _mod, client = admin_client
    resp = client.get("/admin")
    assert resp.status_code == 200
    body = resp.text
    for section in ("overview", "people", "cases", "sanctions", "appeals", "servers", "audit", "site", "tools", "system"):
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


BANNED_SERVER = "1189034578123456789"


@pytest.fixture
def flashes(admin_client, monkeypatch):
    mod, _client = admin_client
    recorded: list[tuple[str, str]] = []
    monkeypatch.setattr(mod, "_push_panel_flash", lambda _request, tone, message: recorded.append((tone, message)))
    return recorded


def _server_sanctions(mod):
    return [item for item in asyncio.run(mod.moderation.list_sanctions()) if item["subjectType"] == "server"]


def _audit(mod, event_type):
    return [event for event in asyncio.run(mod.moderation.list_audit_events()) if event["eventType"] == event_type]


def test_admin_console_lists_blacklisted_servers(admin_client, monkeypatch):
    mod, client = admin_client
    monkeypatch.setattr(
        mod,
        "list_blacklisted_guilds",
        lambda: [
            {
                "guild_id": BANNED_SERVER,
                "name": "Bad Place",
                "reason": "Distributing <illegal> content",
                "actor": "Ada (42)",
                "banned_at": "2026-10-24T06:59:00+00:00",
            }
        ],
    )
    body = client.get("/admin").text
    assert "Bad Place" in body and BANNED_SERVER in body
    assert "Distributing &lt;illegal&gt; content" in body
    assert "24 Oct 2026, 06:59 UTC" in body
    assert '<option value="7">Section Zero</option>' in body

    # A server blacklisted before blacklists were recorded gets its sanction, once.
    client.get("/admin")
    (sanction,) = _server_sanctions(mod)
    assert sanction["serverId"] == BANNED_SERVER and sanction["status"] == "active"
    assert sanction["reason"] == "Distributing <illegal> content"
    assert sanction["startsAt"] == "2026-10-24T06:59:00+00:00"
    assert sanction["metadata"]["actor"]["name"] == "Ada (42)"


def test_blacklisting_a_server_saves_it(admin_client, flashes, monkeypatch):
    mod, client = admin_client

    async def fake_bot_guilds():
        return [{"id": BANNED_SERVER, "name": "Bad Place"}]

    monkeypatch.setattr(mod, "get_bot_guilds", fake_bot_guilds)

    resp = client.post(
        "/admin/servers/blacklist",
        data={"guild_id": BANNED_SERVER, "reason": "Fraud"},
        follow_redirects=False,
    )
    assert resp.status_code == 303 and resp.headers["location"] == "/admin#servers"
    (entry,) = guild_blacklist.list_blacklisted_guilds()
    assert (entry["guild_id"], entry["name"], entry["reason"], entry["actor"]) == (BANNED_SERVER, "Bad Place", "Fraud", "Ada (42)")
    assert flashes == [
        ("success", "Blacklisted Bad Place. Within 10 seconds the bot answers everything there with the ban notice.")
    ]

    (sanction,) = _server_sanctions(mod)
    assert sanction["status"] == "active" and sanction["reason"] == "Fraud"
    assert (sanction["serverId"], sanction["serverName"], sanction["subjectId"]) == (BANNED_SERVER, "Bad Place", None)
    (event,) = _audit(mod, "server.blacklisted")
    assert event["sanctionId"] == sanction["id"]
    assert event["metadata"]["serverId"] == BANNED_SERVER and event["metadata"]["reason"] == "Fraud"
    assert event["metadata"]["actor"] == {"id": "42", "name": "Ada"}


def test_blacklist_refuses_the_home_server(admin_client, flashes, monkeypatch):
    mod, client = admin_client
    monkeypatch.setattr(mod, "GUILD_ID", int(BANNED_SERVER))

    client.post("/admin/servers/blacklist", data={"guild_id": BANNED_SERVER, "reason": "Oops"})
    assert flashes and flashes[0][0] == "error" and "home server" in flashes[0][1]
    assert guild_blacklist.list_blacklisted_guilds() == [] and _server_sanctions(mod) == []


def test_blacklist_reports_invalid_input(admin_client, flashes, monkeypatch):
    mod, client = admin_client
    monkeypatch.setattr(guild_blacklist, "save_json", lambda *_a: pytest.fail("invalid ID was saved"))
    client.post("/admin/servers/blacklist", data={"guild_id": "nope", "reason": "Fraud"})
    assert flashes == [("error", "Enter a valid Discord server ID.")]
    assert _server_sanctions(mod) == [] and _audit(mod, "server.blacklisted") == []


def test_lifting_a_blacklist(admin_client, flashes):
    mod, client = admin_client
    asyncio.run(mod.moderation.blacklist_server(BANNED_SERVER, reason="Fraud", name="Bad Place", actor={"id": "42", "name": "Ada"}))

    resp = client.post("/admin/servers/unblacklist", data={"guild_id": BANNED_SERVER}, follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/admin#servers"
    assert guild_blacklist.list_blacklisted_guilds() == []
    assert flashes[0][0] == "success" and BANNED_SERVER in flashes[0][1]

    (sanction,) = _server_sanctions(mod)
    assert sanction["status"] == "revoked" and sanction["revokeReason"] == "Lifted from the server blacklist"
    (event,) = _audit(mod, "server.unblacklisted")
    assert event["metadata"]["serverName"] == "Bad Place" and event["metadata"]["actor"]["id"] == "42"

    client.post("/admin/servers/unblacklist", data={"guild_id": BANNED_SERVER})
    assert flashes[-1] == ("error", "That server isn't on the blacklist.")
    assert len(_audit(mod, "server.unblacklisted")) == 1


def test_blacklist_routes_are_admin_only(admin_client, monkeypatch):
    mod, client = admin_client

    async def stranger(_request):
        return {"id": "99", "username": "Nobody"}, []

    monkeypatch.setattr(mod, "_load_user_context", stranger)
    monkeypatch.setattr(mod.moderation, "blacklist_server", lambda *_a, **_k: pytest.fail("stranger blacklisted a server"))
    monkeypatch.setattr(mod.moderation, "lift_server_blacklist", lambda *_a, **_k: pytest.fail("stranger lifted a blacklist"))
    assert client.post("/admin/servers/blacklist", data={"guild_id": BANNED_SERVER, "reason": "x"}).status_code == 403
    assert client.post("/admin/servers/unblacklist", data={"guild_id": BANNED_SERVER}).status_code == 403
