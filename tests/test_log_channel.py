import json
import importlib


def test_log_channel_roundtrip(tmp_path, monkeypatch):
    log_file = tmp_path / "log_channel.json"
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")
    main = importlib.import_module("main")
    monkeypatch.setattr(main, "LOG_CHANNEL_FILE", str(log_file))
    assert main.load_log_channel() is None
    main.save_log_channel(123456789)
    assert main.load_log_channel() == 123456789
    assert json.loads(log_file.read_text()) == {"channel_id": 123456789}
