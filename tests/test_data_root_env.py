import importlib
import os


def test_data_root_env_overrides_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")

    util_mod = importlib.reload(importlib.import_module("utils"))
    config_mod = importlib.reload(importlib.import_module("config"))
    main_mod = importlib.reload(importlib.import_module("main"))

    assert util_mod.DOSSIERS_DIR == str(tmp_path)
    assert util_mod.CLEARANCE_FILE == str(tmp_path / "clearance.json")
    assert config_mod.CONFIG_FILE == os.path.join(tmp_path, "log_channel.json")
    assert main_mod.LOG_FILE == os.path.join(tmp_path, "actions.log")
