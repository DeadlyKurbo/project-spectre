import importlib
import asyncio

import utils
from storage_spaces import ensure_dir, save_text, list_dir


def test_execute_epsilon_purges_archive_and_backups(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "DOSSIERS_DIR", tmp_path / "dossiers")
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    main = importlib.reload(importlib.import_module("main"))

    ensure_dir(main.ROOT_PREFIX)
    ensure_dir("backups")
    save_text(f"{main.ROOT_PREFIX}/alpha.txt", "secret")
    save_text("backups/backup.json", "{}")

    async def fake_apply(guild, role):
        pass
    monkeypatch.setattr(main, "apply_protocol_epsilon", fake_apply)

    async def fake_log(*args, **kwargs):
        pass
    monkeypatch.setattr(main, "log_action", fake_log)

    asyncio.run(main.execute_epsilon_actions(None, None))
    asyncio.set_event_loop(asyncio.new_event_loop())

    _dirs, files = list_dir(main.ROOT_PREFIX)
    assert files == []
    _dirs, files = list_dir("backups")
    assert files == []
