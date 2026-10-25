import importlib
import utils


def test_complete_submission_saves_reason(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")
    monkeypatch.setattr(utils, "DOSSIERS_DIR", tmp_path)
    archivist = importlib.reload(importlib.import_module("archivist"))
    sub_id = archivist._save_submission(1, {"type": "upload", "category": "intel", "item": "file.txt", "content": "hi"})
    archivist._complete_submission(1, sub_id, "denied", "fix it")
    data = archivist._load_submission(1, sub_id, "completed")
    assert data["status"] == "denied"
    assert data["reason"] == "fix it"
