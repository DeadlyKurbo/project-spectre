import importlib

def test_load_server_configs_includes_second_guild(tmp_path, monkeypatch):
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("GUILD_ID_SECOND", "2")
    monkeypatch.setenv("MENU_CHANNEL_ID", "10")
    monkeypatch.setenv("MENU_CHANNEL_ID_SECOND", "20")
    import constants
    import server_config
    importlib.reload(constants)
    importlib.reload(server_config)
    missing = tmp_path / "config.json"
    configs = server_config.load_server_configs(str(missing))
    assert 1 in configs and 2 in configs
    assert configs[2].get("GUILD_ID") == 2
    assert configs[1].get("MENU_CHANNEL_ID") == 10
    assert configs[2].get("MENU_CHANNEL_ID") == 20

