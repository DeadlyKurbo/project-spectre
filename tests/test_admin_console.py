import asyncio
import importlib
import sys

import httpx
import pytest

import guild_blacklist
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
    monkeypatch.setattr(mod, "list_blacklisted_guilds", lambda: [])
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


def test_blacklisting_a_server_saves_it_and_removes_the_bot(admin_client, flashes, monkeypatch):
    mod, client = admin_client
    saved = []
    removed = []

    async def fake_bot_guilds():
        return [{"id": BANNED_SERVER, "name": "Bad Place"}]

    def fake_blacklist(guild_id, **kwargs):
        saved.append((guild_id, kwargs))
        return {"guild_id": guild_id, "name": kwargs["name"], "reason": kwargs["reason"], "actor": kwargs["actor"]}

    async def fake_remove(guild_id):
        removed.append(guild_id)
        return True

    monkeypatch.setattr(mod, "get_bot_guilds", fake_bot_guilds)
    monkeypatch.setattr(mod, "blacklist_guild", fake_blacklist)
    monkeypatch.setattr(mod, "_remove_bot_from_guild", fake_remove)

    resp = client.post(
        "/admin/servers/blacklist",
        data={"guild_id": BANNED_SERVER, "reason": "Fraud"},
        follow_redirects=False,
    )
    assert resp.status_code == 303 and resp.headers["location"] == "/admin#servers"
    assert saved == [(BANNED_SERVER, {"reason": "Fraud", "actor": "Ada (42)", "name": "Bad Place"})]
    assert removed == [BANNED_SERVER]
    assert flashes == [("success", "Blacklisted Bad Place. The bot has left and will leave again if re-invited.")]


def test_blacklist_refuses_the_home_server(admin_client, flashes, monkeypatch):
    mod, client = admin_client
    monkeypatch.setattr(mod, "GUILD_ID", int(BANNED_SERVER))
    monkeypatch.setattr(mod, "blacklist_guild", lambda *_a, **_k: pytest.fail("home server was blacklisted"))

    client.post("/admin/servers/blacklist", data={"guild_id": BANNED_SERVER, "reason": "Oops"})
    assert flashes and flashes[0][0] == "error" and "home server" in flashes[0][1]


def test_blacklist_reports_invalid_input(admin_client, flashes, monkeypatch):
    _mod, client = admin_client
    monkeypatch.setattr(guild_blacklist, "save_json", lambda *_a: pytest.fail("invalid ID was saved"))
    client.post("/admin/servers/blacklist", data={"guild_id": "nope", "reason": "Fraud"})
    assert flashes == [("error", "Enter a valid Discord server ID.")]


def test_lifting_a_blacklist(admin_client, flashes, monkeypatch):
    mod, client = admin_client
    lifted = []
    monkeypatch.setattr(mod, "unblacklist_guild", lambda guild_id: lifted.append(guild_id) or True)

    resp = client.post("/admin/servers/unblacklist", data={"guild_id": BANNED_SERVER}, follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/admin#servers"
    assert lifted == [BANNED_SERVER]
    assert flashes[0][0] == "success" and BANNED_SERVER in flashes[0][1]


def test_blacklist_routes_are_admin_only(admin_client, monkeypatch):
    mod, client = admin_client

    async def stranger(_request):
        return {"id": "99", "username": "Nobody"}, []

    monkeypatch.setattr(mod, "_load_user_context", stranger)
    monkeypatch.setattr(mod, "blacklist_guild", lambda *_a, **_k: pytest.fail("stranger blacklisted a server"))
    monkeypatch.setattr(mod, "unblacklist_guild", lambda *_a, **_k: pytest.fail("stranger lifted a blacklist"))
    assert client.post("/admin/servers/blacklist", data={"guild_id": BANNED_SERVER, "reason": "x"}).status_code == 403
    assert client.post("/admin/servers/unblacklist", data={"guild_id": BANNED_SERVER}).status_code == 403


@pytest.mark.parametrize(("status_code", "expected"), [(204, True), (404, False), (500, None)])
def test_remove_bot_from_guild(admin_client, monkeypatch, status_code, expected):
    mod, _client = admin_client
    requests = []

    def handler(request):
        requests.append((request.method, request.url.path, request.headers.get("Authorization")))
        return httpx.Response(status_code)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(mod, "bot_token_available", lambda: True)
    monkeypatch.setattr(mod, "BOT_TOKEN", "bot-token")
    monkeypatch.setattr(
        mod.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)
    )
    mod._bot_guilds_cache = (0.0, [{"id": BANNED_SERVER}])

    assert asyncio.run(mod._remove_bot_from_guild(BANNED_SERVER)) is expected
    method, path, auth = requests[0]
    assert (method, auth) == ("DELETE", "Bot bot-token")
    assert path.endswith(f"/users/@me/guilds/{BANNED_SERVER}")
    assert (mod._bot_guilds_cache is None) == (expected is True)
