import asyncio
import importlib
import sys
import types

import httpx
import pytest
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
    assert resp3.status_code == 404


def test_defaults_when_env_missing(monkeypatch):
    monkeypatch.delenv("DASHBOARD_USERNAME", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    sys.modules.pop("config_app", None)
    mod = importlib.import_module("config_app")
    client = TestClient(mod.app)

    resp = client.get("/configs/123", auth=("admin", "password"))
    assert resp.status_code == 404


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
