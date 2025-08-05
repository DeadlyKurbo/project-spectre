import json
import types
from pathlib import Path

import pytest


@pytest.fixture
def clearance_utils(tmp_path):
    main_path = Path(__file__).resolve().parents[1] / "main.py"
    lines = main_path.read_text().splitlines()
    start = end = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "# —— Paths ——":
            start = idx
        elif stripped == "# —— File listing helpers ——":
            end = idx
            break
    snippet = "\n".join(lines[start:end])
    module = types.ModuleType("clearance_utils")
    module.__file__ = str(main_path)
    exec("import os\nimport json\n" + snippet, module.__dict__)
    sample_file = Path(__file__).with_name("sample_clearance.json")
    temp_file = tmp_path / "clearance.json"
    temp_file.write_text(sample_file.read_text())
    module.CLEARANCE_FILE = str(temp_file)
    return module


def test_get_required_roles_returns_expected_roles(clearance_utils):
    expected = {1365093753035161712, 1365094153901441075}
    assert clearance_utils.get_required_roles("missions", "Operation Iron Veil") == expected


def test_get_required_roles_unknown_returns_empty_set(clearance_utils):
    assert clearance_utils.get_required_roles("unknown_category", "anything") == set()
    assert clearance_utils.get_required_roles("missions", "Unknown Operation") == set()


def test_set_category_clearance_updates_all_items(clearance_utils):
    clearance_utils.set_category_clearance("missions", [1, 2])
    data = clearance_utils.load_clearance()
    assert data["missions"] == {
        "Operation Iron Veil": [1, 2],
        "Operation Ice Crown": [1, 2],
    }


def test_reset_category_clearance_clears_roles(clearance_utils):
    clearance_utils.reset_category_clearance("missions")
    data = clearance_utils.load_clearance()
    assert data["missions"] == {
        "Operation Iron Veil": [],
        "Operation Ice Crown": [],
    }


def test_save_clearance_deduplicates_roles(clearance_utils):
    data = {
        "missions": {
            "Operation Ice Crown": [1, 1, 2]
        }
    }
    clearance_utils.save_clearance(data)
    loaded = clearance_utils.load_clearance()
    assert loaded["missions"]["Operation Ice Crown"] == [1, 2]
