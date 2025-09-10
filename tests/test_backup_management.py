import importlib
import asyncio
from datetime import datetime, UTC

from storage_spaces import ensure_dir, save_text, read_text, list_dir, delete_file, save_json


def _load_main(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        main = importlib.reload(importlib.import_module("main"))
    finally:
        asyncio.set_event_loop(None)
        loop.close()
    return main


def test_backup_retention(monkeypatch):
    main = _load_main(monkeypatch)

    _dirs, files = list_dir("backups")
    for fname, _ in files:
        delete_file(f"backups/{fname}")

    counter = {"n": 0}

    def fake_backup():
        counter["n"] += 1
        fname = f"backups/test{counter['n']}.json"
        save_json(fname, {"n": counter["n"]})
        return datetime.now(UTC), fname

    monkeypatch.setattr(main, "_backup_all", fake_backup)

    for _ in range(5):
        asyncio.run(main._backup_action())

    _dirs, files = list_dir("backups")
    names = sorted(f for f, _ in files)
    assert len(names) == 4
    assert names == ["test2.json", "test3.json", "test4.json", "test5.json"]


def test_restore_backup(monkeypatch):
    main = _load_main(monkeypatch)

    monkeypatch.setattr(main, "ROOT_PREFIX", "testrc")
    ensure_dir("testrc")

    save_text("testrc/foo.txt", "one")
    _ts, fname = main._backup_all()
    save_text("testrc/foo.txt", "two")
    save_text("testrc/bar.txt", "extra")

    main._restore_backup(fname)

    assert read_text("testrc/foo.txt") == "one"
    _dirs, files = list_dir("testrc")
    assert "bar.txt" not in [f for f, _ in files]


def test_backup_filename_greek(monkeypatch):
    main = _load_main(monkeypatch)
    monkeypatch.setattr(main, "ROOT_PREFIX", "testrc")
    ensure_dir("testrc")
    _ts, fname = main._backup_all()
    prefix = "backups/Backup protocol "
    assert fname.startswith(prefix)
    assert fname.endswith(".json")
    core = fname[len(prefix) : -len(".json")]
    letter, ts_str = core.split("-", 1)
    assert letter in main.GREEK_LETTERS
    datetime.strptime(ts_str, "%Y%m%dT%H%M%S")
    delete_file(fname)
