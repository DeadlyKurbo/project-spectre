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

    ensure_dir("backups/global")
    _dirs, files = list_dir("backups/global")
    for fname, _ in files:
        delete_file(f"backups/global/{fname}")

    counter = {"n": 0}

    def fake_backup():
        counter["n"] += 1
        fname = f"backups/global/test{counter['n']}.json"
        save_json(fname, {"n": counter["n"]})
        return datetime.now(UTC), fname

    monkeypatch.setattr(main, "_backup_all", fake_backup)

    for _ in range(5):
        asyncio.run(main._backup_action())

    _dirs, files = list_dir("backups/global")
    names = sorted(f for f, _ in files)
    assert len(names) == 3
    assert names == ["test3.json", "test4.json", "test5.json"]


def test_restore_backup(monkeypatch):
    monkeypatch.setattr("constants.ROOT_PREFIX", "testrc")
    main = _load_main(monkeypatch)

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
    monkeypatch.setattr("constants.ROOT_PREFIX", "testrc")
    main = _load_main(monkeypatch)
    ensure_dir("testrc")
    _ts, fname = main._backup_all()
    prefix = "backups/global/Backup protocol "
    assert fname.startswith(prefix)
    assert fname.endswith(".json")
    core = fname[len(prefix) : -len(".json")]
    letter, ts_str = core.split("-", 1)
    assert letter in main.GREEK_LETTERS
    datetime.strptime(ts_str, "%Y%m%dT%H%M%S")
    delete_file(fname)


def test_backup_skips_zeta_and_alice_chat(monkeypatch):
    import spectre.tasks.backups as backups

    tree = {
        "dossiers": (["alice", "zeta", "personnel"], [("index.json", 2)]),
        "dossiers/personnel": ([], [("file.json", 2)]),
        "dossiers/alice": ([], [("chat-log.json", 2)]),
        "dossiers/zeta": (["dm"], [("members.json", 2)]),
    }
    saved = {}

    def fake_save_text(path, raw, _content_type):
        saved["body"] = raw.read().decode("utf-8")

    monkeypatch.setattr(backups, "list_dir", lambda prefix, limit=10000: tree.get(prefix, ([], [])))
    monkeypatch.setattr(backups, "read_text", lambda path: "{}")
    monkeypatch.setattr(backups, "ensure_dir", lambda path: None)
    monkeypatch.setattr(backups, "save_text", fake_save_text)

    backups.backup_all("dossiers")

    import json as _json
    paths = set(_json.loads(saved["body"]))
    assert paths == {"dossiers/index.json", "dossiers/personnel/file.json"}
