"""Ensure the Discord token resolves from available environment variables."""

import importlib

import constants


def test_token_falls_back_to_bot_token(monkeypatch):
    baseline = constants.TOKEN
    with monkeypatch.context() as ctx:
        ctx.delenv("DISCORD_TOKEN", raising=False)
        ctx.setenv("DISCORD_BOT_TOKEN", "fallback-token")
        module = importlib.reload(constants)
        assert module.TOKEN == "fallback-token"

    importlib.reload(constants)
    assert constants.TOKEN == baseline


def test_token_prefers_primary_over_fallback(monkeypatch):
    baseline = constants.TOKEN
    with monkeypatch.context() as ctx:
        ctx.setenv("DISCORD_TOKEN", "primary-token")
        ctx.setenv("DISCORD_BOT_TOKEN", "fallback-token")
        module = importlib.reload(constants)
        assert module.TOKEN == "primary-token"

    importlib.reload(constants)
    assert constants.TOKEN == baseline
