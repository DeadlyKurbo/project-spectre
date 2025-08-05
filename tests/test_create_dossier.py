import types
import json
from pathlib import Path

import pytest


@pytest.fixture
def file_creation_utils(tmp_path):
    main_path = Path(__file__).resolve().parents[1] / "main.py"
    lines = main_path.read_text().splitlines()
    start = end = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "# —— Paths ——":
            start = idx
        elif stripped == "# —— File Explorer UI ——":
            end = idx
            break
    snippet = "\n".join(lines[start:end])
    module = types.ModuleType("file_creation_utils")
    module.__file__ = str(main_path)
    exec("import os\nimport json\n" + snippet, module.__dict__)
    module.DOSSIERS_DIR = tmp_path
    return module


def test_create_dossier_file_creates_json(file_creation_utils):
    data = {"codename": "Agent A"}
    content = json.dumps(data)
    path = Path(file_creation_utils.create_dossier_file("intel", "agent_a", content))
    assert path.exists()
    assert json.loads(path.read_text()) == data
