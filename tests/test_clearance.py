import json
from pathlib import Path

import pytest

import utils


@pytest.fixture
def clearance_utils(tmp_path):
    sample_file = Path(__file__).with_name("sample_clearance.json")
    temp_file = tmp_path / "clearance.json"
    temp_file.write_text(sample_file.read_text())
    utils.CLEARANCE_FILE = str(temp_file)
    return utils


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
