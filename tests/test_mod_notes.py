import importlib
import utils
from storage_spaces import read_text


def test_add_member_note(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "DOSSIERS_DIR", tmp_path)
    mod_notes = importlib.reload(importlib.import_module("mod_notes"))
    key = mod_notes.add_member_note(123, 456, "test note")
    content = read_text(key)
    assert "<@456>" in content and "test note" in content


def test_list_member_notes(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "DOSSIERS_DIR", tmp_path)
    mod_notes = importlib.reload(importlib.import_module("mod_notes"))
    mod_notes.add_member_note(321, 654, "another note")
    notes = mod_notes.list_member_notes(321)
    assert any("another note" in n for n in notes)
