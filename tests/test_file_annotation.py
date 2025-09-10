import importlib

import utils

from storage_spaces import read_text


def test_add_file_annotation(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "DOSSIERS_DIR", tmp_path)
    annotations = importlib.reload(importlib.import_module("annotations"))
    key = annotations.add_file_annotation(
        "intel", "agent_x", 123456789, "Reviewed 22-08-2025"
    )
    content = read_text(key)
    assert "<@123456789>" in content


def test_list_file_annotations(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "DOSSIERS_DIR", tmp_path)
    annotations = importlib.reload(importlib.import_module("annotations"))
    annotations.add_file_annotation(
        "intel", "agent_x", 987654321, "Reviewed 22-08-2025"
    )
    notes = annotations.list_file_annotations("intel", "agent_x")
    assert any("Reviewed 22-08-2025" in n for n in notes)


def test_edit_and_remove_annotation(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "DOSSIERS_DIR", tmp_path)
    annotations = importlib.reload(importlib.import_module("annotations"))
    annotations.add_file_annotation("intel", "agent_x", 111, "old")
    annotations.update_file_annotation("intel", "agent_x", 0, "new", 111)
    notes = annotations.list_file_annotations("intel", "agent_x")
    assert any("new" in n for n in notes)
    annotations.remove_file_annotation("intel", "agent_x", 0, 111)
    notes = annotations.list_file_annotations("intel", "agent_x")
    assert notes == []
