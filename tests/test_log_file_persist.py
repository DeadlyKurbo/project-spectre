import importlib
import asyncio

def test_log_action_writes_to_file(monkeypatch, tmp_path):
    # Ensure required env vars are present for importing main
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")
    asyncio.set_event_loop(asyncio.new_event_loop())
    main = importlib.reload(importlib.import_module("main"))

    # Disable channel logging and redirect file path
    monkeypatch.setattr(main, "LOG_CHANNEL_ID", None)
    log_file = tmp_path / "actions.log"
    monkeypatch.setattr(main, "LOG_FILE", str(log_file))

    asyncio.run(main.log_action("entry1"))
    assert "entry1" in log_file.read_text()
