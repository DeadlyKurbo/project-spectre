import importlib


def test_remote_config_archive_root_prefix(monkeypatch):
    monkeypatch.setenv("GUILD_ID", "1")
    import server_config

    importlib.reload(server_config)

    def fake_read_json(key, with_etag=False):
        assert key == "guild-configs/99.json"
        doc = {
            "archive": {"root_prefix": " /tcis-archive/ "},
            "settings": {},
        }
        if with_etag:
            return doc, "etag"
        return doc

    monkeypatch.setattr(server_config, "read_json", fake_read_json)
    server_config.invalidate_config()
    cfg = server_config.get_server_config(99)
    assert cfg["ROOT_PREFIX"] == "tcis-archive"
