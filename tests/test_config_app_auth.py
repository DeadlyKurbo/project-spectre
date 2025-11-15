import asyncio
import importlib
import json
import sys
import types

import httpx
import pytest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient


def _load_app(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "pass")
    sys.modules.pop("config_app", None)
    return importlib.import_module("config_app")


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


def test_defaults_when_env_missing(monkeypatch):
    monkeypatch.delenv("DASHBOARD_USERNAME", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    sys.modules.pop("config_app", None)
    mod = importlib.import_module("config_app")
    client = TestClient(mod.app)

    resp = client.get("/configs/123", auth=("admin", "password"))
    assert resp.status_code == 200
    assert resp.json()["_meta"]["exists"] is False


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
