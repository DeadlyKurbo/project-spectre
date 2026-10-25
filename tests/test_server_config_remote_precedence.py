import importlib
import json
from pathlib import Path


def _write_local_config(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload))


def _prime_local(server_config, path: Path) -> None:
    _write_local_config(path, {str(server_config.GUILD_ID): {"ROOT_PREFIX": "local-root"}})
    server_config.SERVER_CONFIGS = server_config.load_server_configs(path)
    server_config._CONFIG_PATH = Path(path)
    try:
        server_config._CONFIG_MTIME = Path(path).stat().st_mtime
    except FileNotFoundError:
        server_config._CONFIG_MTIME = 0.0


def test_remote_config_overrides_local_file(monkeypatch, tmp_path):
    monkeypatch.setenv("GUILD_ID", "1")
    import server_config

    importlib.reload(server_config)

    target = tmp_path / "server_configs.json"
    monkeypatch.setattr(server_config, "_CONFIG_PATH", target)
    _prime_local(server_config, target)

    def fake_read_json(key, with_etag=False):
        assert key == "guild-configs/1.json"
        doc = {"settings": {"ROOT_PREFIX": "remote-root"}}
        if with_etag:
            return doc, "etag"
        return doc

    monkeypatch.setattr(server_config, "read_json", fake_read_json)
    server_config.invalidate_config()

    cfg = server_config.get_server_config(1)
    assert isinstance(cfg, dict)
    assert cfg["ROOT_PREFIX"] == "remote-root"


def test_remote_missing_falls_back_to_local(monkeypatch, tmp_path):
    monkeypatch.setenv("GUILD_ID", "1")
    import server_config

    importlib.reload(server_config)

    target = tmp_path / "server_configs.json"
    monkeypatch.setattr(server_config, "_CONFIG_PATH", target)
    _prime_local(server_config, target)

    def fake_read_json(key, with_etag=False):
        if with_etag:
            return None, None
        return None

    monkeypatch.setattr(server_config, "read_json", fake_read_json)
    server_config.invalidate_config()

    cfg = server_config.get_server_config(1)
    assert isinstance(cfg, server_config.ServerConfig)
    assert cfg.settings["ROOT_PREFIX"] == "local-root"
