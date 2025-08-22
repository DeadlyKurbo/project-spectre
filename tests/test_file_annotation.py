import importlib

import utils

from storage_spaces import read_text


def test_add_file_annotation(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "DOSSIERS_DIR", tmp_path)
    annotations = importlib.reload(importlib.import_module("annotations"))
    key = annotations.add_file_annotation(
        "intel", "agent_x", "Archivist X", "Reviewed 22-08-2025 by Archivist X"
    )
    content = read_text(key)
    assert "Reviewed 22-08-2025 by Archivist X" in content
