import asyncio
import base64
import importlib
import json
import sys
import types

import httpx
import itsdangerous
import pytest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient


def _load_app(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass")
    sys.modules.pop("config_app", None)
    return importlib.import_module("config_app")


def test_landing_page_uses_modern_template(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app, base_url="https://testserver")

    settings = mod.OwnerSettings(
        bot_version="v9.8.7",
        latest_update="Archive relay restored.",
        managers=[],
        fleet_managers=[],
        chat_access=[],
        bot_active=True,
        moderation=mod.ModerationSettings(),
        change_log=[],
    )

    async def fake_load_user_context(_request):  # pragma: no cover - helper stub
        return None, []

    async def fake_bot_facts_block(_user, _request):  # pragma: no cover - helper stub
        return "<div>facts</div>"

    monkeypatch.setattr(mod, "_load_user_context", fake_load_user_context)
    monkeypatch.setattr(mod, "_render_bot_facts_block", fake_bot_facts_block)
    monkeypatch.setattr(mod, "load_owner_settings", lambda: (settings, "etag"))

    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    assert "Intelligence. <span>Reimagined.</span>" in body
    assert "Access Dashboard" in body
    assert "Operator Personalization" in body


def test_landing_page_shows_privileged_links_when_allowed(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)

    settings = mod.OwnerSettings(
        bot_version="v1.0.0",
        latest_update="ready",
        managers=["42"],
        fleet_managers=[],
        chat_access=[],
        bot_active=True,
        moderation=mod.ModerationSettings(),
        change_log=[],
    )

    async def fake_load_user_context(_request):
        return {"id": "42", "username": "Ada", "global_name": "Admiral Ada"}, []

    monkeypatch.setattr(mod, "_load_user_context", fake_load_user_context)
    monkeypatch.setattr(mod, "load_owner_settings", lambda: (settings, "etag"))
    monkeypatch.setattr(mod, "_session_user_is_owner", lambda _request: True)

    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    assert "Director Console" in body
    assert "Enter Admin Mode" in body
    assert "data-display-name=\"Admiral Ada\"" in body


def test_maintenance_screen_blocks_non_admin(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app, base_url="https://testserver")

    state = {
        "enabled": True,
        "message": mod.SITE_LOCK_MESSAGE_DEFAULT,
        "actor": "Operator",
        "enabled_at": "2024-01-01T00:00:00Z",
    }

    async def fake_bot_facts(_user, _request):
        return "<div>facts</div>"

    monkeypatch.setattr(mod, "get_site_lock_state", lambda: state)
    monkeypatch.setattr(mod, "_render_bot_facts_block", fake_bot_facts)

    resp = client.get("/")
    assert resp.status_code == 503
    assert "Maintenance" in resp.text
    assert "Operator" in resp.text


def test_maintenance_allows_admin_sessions(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)

    settings = mod.OwnerSettings(
        bot_version="v1",
        latest_update="msg",
        managers=["42"],
        fleet_managers=[],
        chat_access=[],
        bot_active=True,
        moderation=mod.ModerationSettings(),
        change_log=[],
    )

    async def fake_load_user_context(_request):
        return {"id": "42", "username": "Ada", "discriminator": "1"}, []

    async def fake_bot_facts(_user, _request):
        return "<div>facts</div>"

    monkeypatch.setattr(mod, "get_site_lock_state", lambda: {
        "enabled": True,
        "message": mod.SITE_LOCK_MESSAGE_DEFAULT,
        "actor": None,
        "enabled_at": None,
    })
    monkeypatch.setattr(mod, "_session_user_is_admin", lambda request: True)
    monkeypatch.setattr(mod, "_load_user_context", fake_load_user_context)
    monkeypatch.setattr(mod, "_render_bot_facts_block", fake_bot_facts)
    monkeypatch.setattr(mod, "load_owner_settings", lambda: (settings, "etag"))
    monkeypatch.setattr(mod, "get_system_health_state", lambda: {"status": "online", "note": ""})

    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "Configuration Console" in resp.text
    assert "Maintenance mode" not in resp.text


def test_maintenance_allows_basic_auth(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)

    state = {
        "enabled": True,
        "message": mod.SITE_LOCK_MESSAGE_DEFAULT,
        "actor": None,
        "enabled_at": None,
    }

    async def fake_summary():
        return ({"status": "ok"}, None)

    monkeypatch.setattr(mod, "get_site_lock_state", lambda: state)
    monkeypatch.setattr(mod, "_collect_hd2_summary", fake_summary)

    resp = client.get("/api/hd2/summary", auth=("user", "pass"))
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_maintenance_bypass_allows_lock_actor(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app, base_url="https://testserver")

    token = {"access_token": "token-value", "expires_in": 100}
    monkeypatch.setattr(mod.oauth, "fetch_token", lambda *a, **k: token)

    user = {"id": "1059522006602752150", "username": "DeadlyKurbo", "discriminator": "0001"}

    class DummyResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class DummyAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *, headers):  # pragma: no cover - assertions inside
            assert headers == {"Authorization": "Bearer token-value"}
            assert url.endswith("/users/@me")
            return DummyResponse(user)

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda: DummyAsyncClient())

    resp = client.get("/callback?code=abc&state=xyz", follow_redirects=False)
    assert resp.status_code == 307

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

    async def fake_load_user_context(_request):
        return user, []

    async def fake_bot_facts(_user, _request):
        return "<div>facts</div>"

    state = {
        "enabled": True,
        "message": mod.SITE_LOCK_MESSAGE_DEFAULT,
        "actor": "DeadlyKurbo (1059522006602752150)",
        "enabled_at": "2024-01-01T00:00:00Z",
    }

    monkeypatch.setattr(mod, "get_site_lock_state", lambda: state)
    monkeypatch.setattr(mod, "load_owner_settings", lambda: (settings, "etag"))
    monkeypatch.setattr(mod, "_load_user_context", fake_load_user_context)
    monkeypatch.setattr(mod, "_render_bot_facts_block", fake_bot_facts)

    resp = client.get("/")
    assert resp.status_code == 200


def test_admin_cannot_enable_maintenance(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)

    async def fake_require_director(_request):
        raise mod.HTTPException(
            mod.status.HTTP_403_FORBIDDEN, detail="You do not have access to the director console."
        )

    monkeypatch.setattr(mod, "_require_director", fake_require_director)

    resp = client.post("/admin/maintenance", data={"mode": "enable"}, follow_redirects=False)
    assert resp.status_code == 403


def test_director_can_enable_maintenance(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)

    user = {"id": "99", "username": "Nova", "discriminator": "1234"}
    state = {
        "enabled": False,
        "message": mod.SITE_LOCK_MESSAGE_DEFAULT,
        "actor": None,
        "enabled_at": None,
    }

    async def fake_require_director(_request):
        return user, None

    def fake_set_lock(enabled, *, actor=None, message=None):
        state.update({
            "enabled": enabled,
            "actor": actor,
            "message": message or state.get("message"),
        })

    def fake_get_lock_state():
        return state

    monkeypatch.setattr(mod, "_require_director", fake_require_director)
    monkeypatch.setattr(mod, "set_site_lock_state", fake_set_lock)
    monkeypatch.setattr(mod, "get_site_lock_state", fake_get_lock_state)

    resp = client.post("/director/maintenance", json={"enabled": True})
    assert resp.status_code == 200
    assert state["enabled"] is True
    assert state["actor"] == "Nova#1234 (99)"


def test_callback_populates_session_user_for_maintenance_bypass(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app, base_url="https://testserver")

    token = {"access_token": "token-value", "expires_in": 100}
    monkeypatch.setattr(mod.oauth, "fetch_token", lambda *a, **k: token)

    user = {"id": "42", "username": "Ada", "discriminator": "0001"}

    class DummyResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class DummyAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *, headers):  # pragma: no cover - assertions inside
            assert headers == {"Authorization": "Bearer token-value"}
            return DummyResponse(user)

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda: DummyAsyncClient())

    resp = client.get("/callback?code=abc&state=xyz", follow_redirects=False)
    assert resp.status_code == 307

    cookie_value = client.cookies.get(mod.SESSION_COOKIE_NAME)
    assert cookie_value

    signer = itsdangerous.TimestampSigner(str(mod.SESSION_SECRET))
    payload = signer.unsign(cookie_value.encode("utf-8"))
    session_data = json.loads(base64.b64decode(payload))
    assert session_data["user"] == user

    settings = mod.OwnerSettings(
        bot_version="v1",
        latest_update="msg",
        managers=["42"],
        fleet_managers=[],
        chat_access=[],
        bot_active=True,
        moderation=mod.ModerationSettings(),
        change_log=[],
    )

    monkeypatch.setattr(mod, "load_owner_settings", lambda: (settings, "etag"))
    request = types.SimpleNamespace(session=session_data)
    assert mod._session_user_is_admin(request) is True
def test_basic_auth_required(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)

    resp = client.get("/configs/123")
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Basic"

    resp2 = client.get("/configs/123", auth=("user", "wrong"))
    assert resp2.status_code == 401
    assert resp2.headers.get("WWW-Authenticate") == "Basic"

    resp3 = client.get("/configs/123", auth=("user", "pass"))
    assert resp3.status_code == 200
    body = resp3.json()
    assert body["_meta"]["exists"] is False
    assert body["_meta"]["etag"] is None
    assert body["settings"] == {}


def test_pyro_war_redirects_on_outcome(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app, base_url="https://testserver")

    monkeypatch.setattr(mod, "_session_user_is_admin", lambda request: False)
    monkeypatch.setattr(mod, "_session_user_is_owner", lambda request: False)
    monkeypatch.setattr(
        mod,
        "load_pyro_war_state",
        lambda: {
            "battle_readiness": {},
            "attack_focus": "",
            "fleet_assignments": {},
            "war_status": "victory",
            "war_outcome_message": "Pyro secured.",
        },
    )
    monkeypatch.setattr(mod, "load_fleet_manifest", lambda: (types.SimpleNamespace(vessels=[]), None))

    resp = client.get("/operations/pyro-war", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/operations/pyro-war/victory")


def test_pyro_war_allows_admin_view_after_withdrawal(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app, base_url="https://testserver")

    monkeypatch.setattr(mod, "_session_user_is_admin", lambda request: True)
    monkeypatch.setattr(mod, "_session_user_is_owner", lambda request: False)
    monkeypatch.setattr(
        mod,
        "load_pyro_war_state",
        lambda: {
            "battle_readiness": {},
            "attack_focus": "",
            "fleet_assignments": {},
            "war_status": "retreat",
            "war_outcome_message": "Fall back to regroup.",
        },
    )
    monkeypatch.setattr(mod, "load_fleet_manifest", lambda: (types.SimpleNamespace(vessels=[]), None))

    resp = client.get("/operations/pyro-war")
    assert resp.status_code == 200
    assert "Strategic withdrawal" in resp.text


def test_pyro_war_is_hidden_during_peace(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app, base_url="https://testserver")

    monkeypatch.setattr(mod, "_session_user_is_admin", lambda request: False)
    monkeypatch.setattr(mod, "_session_user_is_owner", lambda request: False)
    monkeypatch.setattr(
        mod,
        "load_pyro_war_state",
        lambda: {
            "battle_readiness": {},
            "attack_focus": "",
            "fleet_assignments": {},
            "war_status": "peace",
            "war_outcome_message": "Ceasefire declared.",
        },
    )
    monkeypatch.setattr(mod, "load_fleet_manifest", lambda: (types.SimpleNamespace(vessels=[]), None))

    resp = client.get("/operations/pyro-war")
    assert resp.status_code == 404


def test_pyro_war_admin_redirects_to_manager_when_hidden(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app, base_url="https://testserver")

    monkeypatch.setattr(mod, "_session_user_is_admin", lambda request: True)
    monkeypatch.setattr(mod, "_session_user_is_owner", lambda request: False)
    monkeypatch.setattr(
        mod,
        "load_pyro_war_state",
        lambda: {
            "battle_readiness": {},
            "attack_focus": "",
            "fleet_assignments": {},
            "war_status": "peace",
            "war_outcome_message": "Ceasefire declared.",
        },
    )
    monkeypatch.setattr(mod, "load_fleet_manifest", lambda: (types.SimpleNamespace(vessels=[]), None))

    resp = client.get("/operations/pyro-war", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/admin/war-manager")


def test_defaults_when_env_missing(monkeypatch):
    monkeypatch.delenv("DASHBOARD_USERNAME", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    sys.modules.pop("config_app", None)
    mod = importlib.import_module("config_app")
    client = TestClient(mod.app)

    resp = client.get("/configs/123", auth=("admin", "password"))
    assert resp.status_code == 200
    assert resp.json()["_meta"]["exists"] is False


def test_load_user_context_clears_expired_session(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("DISCORD_CLIENT_ID", "client")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "secret")
    monkeypatch.setenv("DISCORD_REDIRECT_URI", "https://example.com/callback")
    mod = _load_app(monkeypatch)

    async def fake_user_guilds(_token):  # pragma: no cover - validated via exception
        response = httpx.Response(
            status_code=401,
            request=httpx.Request("GET", "https://discord.example/api"),
        )
        raise httpx.HTTPStatusError(
            "unauthorized", request=response.request, response=response
        )

    monkeypatch.setattr(mod, "get_user_guilds", fake_user_guilds)

    request = types.SimpleNamespace(
        session={
            "discord_token": {"access_token": "token"},
            "user": {"id": "42"},
            "guilds": ["123"],
            "bot_guild_count": 5,
        }
    )

    async def exercise():
        user, guilds = await mod._load_user_context(request)

        assert user is None
        assert guilds == []
        assert "discord_token" not in request.session
        assert "user" not in request.session
        assert "guilds" not in request.session
        assert "bot_guild_count" not in request.session

    asyncio.run(exercise())


def test_check_access_handles_expired_session(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("DISCORD_CLIENT_ID", "client")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "secret")
    monkeypatch.setenv("DISCORD_REDIRECT_URI", "https://example.com/callback")
    mod = _load_app(monkeypatch)

    async def fake_user_guilds(token):  # pragma: no cover - behaviour validated via exception
        response = httpx.Response(
            status_code=401,
            request=httpx.Request("GET", "https://discord.example/api"),
        )
        raise httpx.HTTPStatusError("unauthorized", request=response.request, response=response)

    async def fake_bot_guilds():
        return []

    monkeypatch.setattr(mod, "get_user_guilds", fake_user_guilds)
    monkeypatch.setattr(mod, "get_bot_guilds", fake_bot_guilds)

    request = types.SimpleNamespace(
        session={
            "discord_token": {"access_token": "token"},
            "user": {"id": "42"},
            "guilds": ["123"],
        }
    )

    async def exercise():
        with pytest.raises(mod.HTTPException) as excinfo:
            await mod._check_access(request, "123")

        assert excinfo.value.status_code == mod.status.HTTP_401_UNAUTHORIZED
        assert "expired" in excinfo.value.detail
        assert "discord_token" not in request.session
        assert "user" not in request.session

    asyncio.run(exercise())


def test_check_access_uses_cached_guilds(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("DISCORD_CLIENT_ID", "client")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "secret")
    monkeypatch.setenv("DISCORD_REDIRECT_URI", "https://example.com/callback")
    mod = _load_app(monkeypatch)

    async def unexpected(*_args, **_kwargs):  # pragma: no cover - should not run
        raise AssertionError("Discord APIs should not be called when cache is valid")

    monkeypatch.setattr(mod, "get_user_guilds", unexpected)
    monkeypatch.setattr(mod, "get_bot_guilds", unexpected)

    request = types.SimpleNamespace(
        session={
            "discord_token": {"access_token": "token"},
            "guilds": [{"id": "123"}, {"id": "456"}],
        }
    )

    async def exercise():
        assert await mod._check_access(request, "123") is True

    asyncio.run(exercise())


def test_check_access_refreshes_cache(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("DISCORD_CLIENT_ID", "client")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "secret")
    monkeypatch.setenv("DISCORD_REDIRECT_URI", "https://example.com/callback")
    mod = _load_app(monkeypatch)

    async def fake_user_guilds(_token):
        return [{"id": "123", "permissions": str(mod.MANAGE_GUILD)}]

    async def fake_bot_guilds():
        return [{"id": "123"}]

    monkeypatch.setattr(mod, "get_user_guilds", fake_user_guilds)
    monkeypatch.setattr(mod, "get_bot_guilds", fake_bot_guilds)

    request = types.SimpleNamespace(
        session={
            "discord_token": {"access_token": "token"},
            "guilds": [],
        }
    )

    async def exercise():
        assert await mod._check_access(request, "123") is True

    asyncio.run(exercise())

    assert request.session["guilds"] == [
        {"id": "123", "permissions": str(mod.MANAGE_GUILD)}
    ]
    assert request.session["bot_guild_count"] == 1


def test_check_access_allows_without_bot_token(monkeypatch):
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.setenv("DISCORD_CLIENT_ID", "client")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "secret")
    monkeypatch.setenv("DISCORD_REDIRECT_URI", "https://example.com/callback")
    mod = _load_app(monkeypatch)

    async def fake_user_guilds(_token):
        return [{"id": "123", "permissions": str(mod.MANAGE_GUILD)}]

    async def unexpected(*_args, **_kwargs):  # pragma: no cover - should not run
        raise AssertionError("Bot guild lookup should be skipped when token missing")

    monkeypatch.setattr(mod, "get_user_guilds", fake_user_guilds)
    monkeypatch.setattr(mod, "get_bot_guilds", unexpected)

    request = types.SimpleNamespace(
        session={
            "discord_token": {"access_token": "token"},
            "guilds": [],
        }
    )

    async def exercise():
        assert await mod._check_access(request, "123") is True

    asyncio.run(exercise())

    assert request.session["guilds"] == [
        {"id": "123", "permissions": str(mod.MANAGE_GUILD)}
    ]
    assert "bot_guild_count" not in request.session


def test_delete_guild_config_clears_storage(monkeypatch):
    mod = _load_app(monkeypatch)

    guild_id = "123"
    stored_doc = {"settings": {"menu_theme": "dark"}}

    def fake_read_json(key, *, with_etag=False):
        assert key == mod.guild_key(guild_id)
        assert with_etag is True
        return stored_doc, "etag-value"

    backups = []
    monkeypatch.setattr(mod, "read_json", fake_read_json)
    monkeypatch.setattr(mod, "backup_json", lambda name, data: backups.append((name, data)))

    deleted_keys = []

    def fake_delete_file(key):
        deleted_keys.append(key)

    monkeypatch.setattr(mod, "delete_file", fake_delete_file)

    invalidated = []
    monkeypatch.setattr(mod, "invalidate_config", lambda gid: invalidated.append(gid))

    resets = []
    monkeypatch.setattr(mod, "_invalidate_config_count_cache", lambda: resets.append(True))

    request = types.SimpleNamespace(session={})

    async def exercise():
        return await mod.delete_guild_config(guild_id, request, True)

    response = asyncio.run(exercise())

    assert deleted_keys == [mod.guild_key(guild_id)]
    assert backups == [(f"{guild_id}.json", stored_doc)]
    assert invalidated == [guild_id]
    assert resets == [True]
    assert response.status_code == 200
    payload = json.loads(response.body.decode("utf-8"))
    assert payload == {"ok": True, "deleted": True}


def test_delete_guild_config_missing_document(monkeypatch):
    mod = _load_app(monkeypatch)

    monkeypatch.setattr(mod, "read_json", lambda *_args, **_kwargs: (None, None))
    backups = []
    monkeypatch.setattr(mod, "backup_json", lambda *args, **kwargs: backups.append(True))

    deleted = []
    monkeypatch.setattr(mod, "delete_file", lambda key: deleted.append(key))

    invalidated = []
    monkeypatch.setattr(mod, "invalidate_config", lambda gid: invalidated.append(gid))

    resets = []
    monkeypatch.setattr(mod, "_invalidate_config_count_cache", lambda: resets.append(True))

    request = types.SimpleNamespace(session={})

    async def exercise():
        return await mod.delete_guild_config("999", request, True)

    response = asyncio.run(exercise())

    assert deleted == [mod.guild_key("999")]
    assert invalidated == ["999"]
    assert resets == [True]
    assert backups == []
    payload = json.loads(response.body.decode("utf-8"))
    assert payload == {"ok": True, "deleted": False}


def test_put_guild_config_invalidates_caches(monkeypatch):
    mod = _load_app(monkeypatch)

    class DummyRequest:
        def __init__(self, payload):
            self._payload = payload
            self.session = {}

        async def json(self):
            return self._payload

    payload = {
        "settings": {"menu_theme": "tcis"},
        "_meta": {"etag": "client-tag"},
    }

    request = DummyRequest(payload)

    monkeypatch.setattr(mod, "read_json", lambda *_args, **_kwargs: (None, None))

    writes = []

    def fake_write_json(key, data, *, etag=None):
        writes.append((key, data, etag))
        return True

    monkeypatch.setattr(mod, "write_json", fake_write_json)

    def forbid_backup(*_args, **_kwargs):
        raise AssertionError("backup should not run")

    monkeypatch.setattr(mod, "backup_json", forbid_backup)

    invalidated = []
    monkeypatch.setattr(mod, "invalidate_config", lambda gid: invalidated.append(gid))

    resets = []
    monkeypatch.setattr(mod, "_invalidate_config_count_cache", lambda: resets.append(True))

    async def exercise():
        return await mod.put_guild_config("456", request, True)

    result = asyncio.run(exercise())

    assert result == {"ok": True}
    assert writes == [
        (mod.guild_key("456"), {"settings": {"menu_theme": "tcis"}}, "client-tag")
    ]
    assert invalidated == ["456"]
    assert resets == [True]


def test_put_guild_config_sanitises_clearance(monkeypatch):
    mod = _load_app(monkeypatch)

    class DummyRequest:
        def __init__(self, payload):
            self._payload = payload
            self.session = {}

        async def json(self):
            return self._payload

    payload = {
        "settings": {
            "clearance": {
                "levels": {
                    "1": {"name": "  Confidential  ", "roles": ["111", "222", "111", "oops"]},
                    "02": {"name": "  ", "roles": ["333"]},
                    "3": {"roles": [444, "bad"]},
                    "9": {"roles": [999]},
                    "bad": {"name": "Invalid"},
                    "6": {"name": "Classified", "roles": []},
                    "5": "ignored",
                },
                "other": "keepme",
            }
        },
        "_meta": {"etag": None},
    }

    request = DummyRequest(payload)

    monkeypatch.setattr(mod, "read_json", lambda *_args, **_kwargs: (None, None))

    async def fake_run_blocking(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(mod, "run_blocking", fake_run_blocking)
    monkeypatch.setattr(mod, "ensure_guild_archive_structure", lambda *a, **k: None)

    writes = []

    def fake_write_json(key, data, *, etag=None):
        writes.append((key, data, etag))
        return True

    monkeypatch.setattr(mod, "write_json", fake_write_json)
    monkeypatch.setattr(mod, "register_archive", lambda *a, **k: None)
    monkeypatch.setattr(mod, "save_json", lambda *a, **k: None)

    invalidated = []
    monkeypatch.setattr(mod, "invalidate_config", lambda gid: invalidated.append(gid))
    resets = []
    monkeypatch.setattr(mod, "_invalidate_config_count_cache", lambda: resets.append(True))

    async def exercise():
        return await mod.put_guild_config("321", request, True)

    result = asyncio.run(exercise())

    assert result == {"ok": True}
    assert invalidated == ["321"]
    assert resets == [True]
    assert len(writes) == 1
    key, stored, etag = writes[0]
    assert key == mod.guild_key("321")
    assert etag is None
    levels = stored["settings"]["clearance"]["levels"]
    assert levels == {
        "1": {"name": "Confidential", "roles": [111, 222]},
        "2": {"roles": [333]},
        "3": {"roles": [444]},
        "6": {"name": "Classified"},
    }
    assert stored["settings"]["clearance"]["other"] == "keepme"
    assert stored["clearance"] == stored["settings"]["clearance"]


def test_put_guild_config_preserves_existing_clearance_when_not_in_payload(monkeypatch):
    mod = _load_app(monkeypatch)

    class DummyRequest:
        def __init__(self, payload):
            self._payload = payload
            self.session = {}

        async def json(self):
            return self._payload

    payload = {
        "settings": {
            "channels": {"menu_home": "123456789012345678"},
        },
        "_meta": {"etag": "client-tag"},
    }

    request = DummyRequest(payload)

    existing = {
        "settings": {
            "clearance": {
                "levels": {
                    "1": {"name": "Confidential", "roles": [111111111111111111]},
                    "3": {"roles": [333333333333333333]},
                }
            }
        }
    }

    def fake_read_json(*_args, **_kwargs):
        return existing, "server-tag"

    monkeypatch.setattr(mod, "read_json", fake_read_json)

    async def fake_run_blocking(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(mod, "run_blocking", fake_run_blocking)
    monkeypatch.setattr(mod, "ensure_guild_archive_structure", lambda *a, **k: None)

    writes = []

    def fake_write_json(key, data, *, etag=None):
        writes.append((key, data, etag))
        return True

    monkeypatch.setattr(mod, "write_json", fake_write_json)
    monkeypatch.setattr(mod, "backup_json", lambda *a, **k: None)
    monkeypatch.setattr(mod, "register_archive", lambda *a, **k: None)
    monkeypatch.setattr(mod, "save_json", lambda *a, **k: None)
    monkeypatch.setattr(mod, "invalidate_config", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_invalidate_config_count_cache", lambda: None)

    async def exercise():
        return await mod.put_guild_config("321", request, True)

    result = asyncio.run(exercise())

    assert result == {"ok": True}
    assert len(writes) == 1
    _key, stored, etag = writes[0]
    assert etag == "client-tag"
    assert stored["settings"]["clearance"]["levels"] == {
        "1": {"name": "Confidential", "roles": [111111111111111111]},
        "3": {"roles": [333333333333333333]},
    }


def test_request_guild_deploy_enqueues_queue_item(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)

    guild_id = "555"
    stored_doc = {"settings": {"channels": {"menu_home": "999"}}}

    def fake_read_json(key, *, with_etag=False):
        assert key == mod.guild_key(guild_id)
        assert with_etag is True
        return stored_doc, "etag"

    saved = []
    local_triggers: list[int] = []

    def fake_save_json(key, payload):
        saved.append((key, payload))

    monkeypatch.setattr(mod, "read_json", fake_read_json)
    monkeypatch.setattr(mod, "save_json", fake_save_json)
    monkeypatch.setattr(mod, "request_deploy", lambda gid_int, reason="": local_triggers.append(gid_int))

    resp = client.post(f"/configs/{guild_id}/deploy", auth=("user", "pass"))

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "queued_at" in body
    assert body["menu_channel_id"] == 999
    assert len(saved) == 1
    queue_key, queue_payload = saved[0]
    assert queue_key == f"deploy-queue/{guild_id}.json"
    assert queue_payload["menu_channel_id"] == 999
    assert queue_payload["trigger"] == "manual_dashboard_deploy"
    assert "queued_at" in queue_payload
    assert local_triggers == [int(guild_id)]


def test_request_guild_deploy_requires_menu_channel(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app)

    def fake_read_json(key, *, with_etag=False):
        return {"settings": {}}, "etag"

    monkeypatch.setattr(mod, "read_json", fake_read_json)

    called = []
    monkeypatch.setattr(mod, "save_json", lambda *args, **kwargs: called.append(True))
    monkeypatch.setattr(mod, "request_deploy", lambda *args, **kwargs: called.append(True))

    resp = client.post("/configs/123/deploy", auth=("user", "pass"))

    assert resp.status_code == 400
    assert "menu channel" in resp.json()["detail"].lower()
    assert called == []


def test_dashboard_origin_configures_cors(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass")
    monkeypatch.setenv("DASHBOARD_ORIGIN", "https://panel.example")
    monkeypatch.setenv("DISCORD_REDIRECT_URI", "https://other.example/oauth")
    sys.modules.pop("config_app", None)
    mod = importlib.import_module("config_app")

    session_middleware = [mw for mw in mod.app.user_middleware if mw.cls is mod.SessionMiddleware]
    assert len(session_middleware) == 1

    cors_middleware = [mw for mw in mod.app.user_middleware if mw.cls is CORSMiddleware]
    assert len(cors_middleware) == 1
    assert cors_middleware[0].kwargs.get("allow_credentials") is True
    assert cors_middleware[0].kwargs.get("allow_origins") == ["https://panel.example"]

    assert mod.REDIRECT_URI == "https://panel.example/oauth"


def test_session_cookie_defaults_to_lax(monkeypatch):
    mod = _load_app(monkeypatch)

    session_middleware = [mw for mw in mod.app.user_middleware if mw.cls is mod.SessionMiddleware]
    assert len(session_middleware) == 1
    assert session_middleware[0].kwargs.get("same_site") == "lax"
    assert session_middleware[0].kwargs.get("https_only") is True


def test_invalid_session_cookie_same_site_falls_back_to_lax(monkeypatch):
    monkeypatch.setenv("SESSION_COOKIE_SAMESITE", "invalid")
    mod = _load_app(monkeypatch)

    assert mod.SESSION_COOKIE_SAMESITE == "lax"

    session_middleware = [mw for mw in mod.app.user_middleware if mw.cls is mod.SessionMiddleware]
    assert len(session_middleware) == 1
    assert session_middleware[0].kwargs.get("same_site") == "lax"


def test_landing_features_link_targets_dedicated_page(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app, base_url="https://testserver")

    settings = mod.OwnerSettings(
        bot_version="v1",
        latest_update="ready",
        managers=[],
        fleet_managers=[],
        chat_access=[],
        bot_active=True,
        moderation=mod.ModerationSettings(),
        change_log=[],
    )

    async def fake_load_user_context(_request):
        return None, []

    monkeypatch.setattr(mod, "_load_user_context", fake_load_user_context)
    monkeypatch.setattr(mod, "load_owner_settings", lambda: (settings, "etag"))

    resp = client.get("/")
    assert resp.status_code == 200
    assert '<a href="/features">Features</a>' in resp.text
    assert 'href="/features" class="btn btn-outline">Explore Features</a>' in resp.text


def test_features_page_renders_core_capabilities(monkeypatch):
    mod = _load_app(monkeypatch)
    client = TestClient(mod.app, base_url="https://testserver")

    async def fake_load_user_context(_request):
        return {"username": "Ada", "global_name": "Commander Ada"}, []

    monkeypatch.setattr(mod, "_load_user_context", fake_load_user_context)

    resp = client.get("/features")
    assert resp.status_code == 200
    body = resp.text
    assert "Spectre Capability Atlas" in body
    assert "AEGIS Identity & Access" in body
    assert "ALICE Intelligence Assistant" in body
    assert "War Map Operations" in body
    assert 'data-display-name="Commander Ada"' in body
