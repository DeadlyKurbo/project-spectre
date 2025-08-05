import types
from pathlib import Path

import pytest


@pytest.fixture
def clearance_utils():
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
    module.CLEARANCE_FILE = str(sample_file)
    return module


def test_get_required_roles_returns_expected_roles(clearance_utils):
    expected = {1365093753035161712, 1365094153901441075}
    assert clearance_utils.get_required_roles("missions", "Operation Iron Veil") == expected


def test_get_required_roles_unknown_returns_empty_set(clearance_utils):
    assert clearance_utils.get_required_roles("unknown_category", "anything") == set()
    assert clearance_utils.get_required_roles("missions", "Unknown Operation") == set()
