"""Tests for ``server_config.configured_guild_ids`` helper."""

from __future__ import annotations

import importlib


def _reload_server_config(monkeypatch, env_value: str) -> None:
    monkeypatch.setenv("GUILD_ID", env_value)
    import constants
    import server_config

    importlib.reload(constants)
    importlib.reload(server_config)


def test_configured_guild_ids_filters_invalid_entries(monkeypatch):
    _reload_server_config(monkeypatch, "0")
    import server_config

    server_config.SERVER_CONFIGS = {
        -1: server_config.ServerConfig({}),
        0: server_config.ServerConfig({}),
        42: server_config.ServerConfig({}),
    }

    assert server_config.configured_guild_ids() == [42]


def test_configured_guild_ids_falls_back_to_env_when_empty(monkeypatch):
    _reload_server_config(monkeypatch, "987654")
    import server_config

    server_config.SERVER_CONFIGS = {}

    assert server_config.configured_guild_ids() == [987654]
