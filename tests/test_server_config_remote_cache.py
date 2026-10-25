import json

import server_config


def test_remote_config_persisted_to_cache(tmp_path, monkeypatch):
    cache_path = tmp_path / "cache.json"
    config_path = tmp_path / "server_configs.json"

    monkeypatch.setattr(server_config, "_REMOTE_CACHE_PATH", cache_path)
    monkeypatch.setattr(server_config, "_CONFIG_PATH", config_path)
    monkeypatch.setattr(server_config, "SERVER_CONFIGS", {})
    monkeypatch.setattr(server_config, "_CONFIG_MTIME", 0.0)

    def fake_remote(guild_id):
        return {"GUILD_ID": guild_id, "TOKEN": "example-token", "MENU_CHANNEL_ID": 999}

    monkeypatch.setattr(server_config, "_get_remote_config", fake_remote)

    cfg = server_config.get_server_config(42)

    assert cfg["TOKEN"] == "example-token"
    assert cache_path.exists()
    cached = json.loads(cache_path.read_text())
    assert cached == {"42": cfg}


def test_cached_remote_used_when_unavailable(tmp_path, monkeypatch):
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps({"7": {"GUILD_ID": 7, "TOKEN": "cached-token"}}))

    monkeypatch.setattr(server_config, "_REMOTE_CACHE_PATH", cache_path)
    monkeypatch.setattr(server_config, "_CONFIG_PATH", tmp_path / "server_configs.json")
    monkeypatch.setattr(server_config, "SERVER_CONFIGS", {})
    monkeypatch.setattr(server_config, "_CONFIG_MTIME", 0.0)

    def failing_remote(_guild_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(server_config, "_get_remote_config", failing_remote)

    cfg = server_config.get_server_config(7)

    assert cfg["TOKEN"] == "cached-token"
