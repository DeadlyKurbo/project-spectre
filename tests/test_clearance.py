from pathlib import Path

import pytest

import utils


@pytest.fixture
def clearance_utils(tmp_path):
    sample_file = Path(__file__).with_name("sample_clearance.json")
    temp_file = tmp_path / "clearance.json"
    temp_file.write_text(sample_file.read_text())
    utils.CLEARANCE_FILE = str(temp_file)

    dossiers = tmp_path / "dossiers"
    # Create minimal dossier structure required by the tests
    (dossiers / "missions").mkdir(parents=True)
    (dossiers / "missions" / "Operation Iron Veil.json").write_text("{}")
    (dossiers / "missions" / "Operation Ice Crown.json").write_text("{}")
    (dossiers / "fleet").mkdir()
    (dossiers / "fleet" / "EXAMPLE SHIP.json").write_text("{}")
    (dossiers / "intel").mkdir()
    (dossiers / "intel" / "EXAMPLE INTEL.json").write_text("{}")
    (dossiers / "personnel").mkdir()
    (dossiers / "personnel" / "EXAMPLE PERSONNEL.json").write_text("{}")
    utils.DOSSIERS_DIR = str(dossiers)
    return utils


def test_get_required_roles_returns_expected_roles(clearance_utils):
    expected = {1365093753035161712, 1402635734506016861}
    assert clearance_utils.get_required_roles("missions", "Operation Iron Veil") == expected


def test_get_required_roles_unknown_returns_empty_set(clearance_utils):
    assert clearance_utils.get_required_roles("unknown_category", "anything") == set()
    assert clearance_utils.get_required_roles("missions", "Unknown Operation") == set()


def test_set_category_clearance_updates_all_items(clearance_utils):
    clearance_utils.set_category_clearance("missions", [1, 2])
    data = clearance_utils.load_clearance()
    expected = {
        name: [1, 2] for name in clearance_utils.list_items("missions")
    }
    assert data["missions"] == expected


def test_reset_category_clearance_clears_roles(clearance_utils):
    clearance_utils.reset_category_clearance("missions")
    data = clearance_utils.load_clearance()
    expected = {name: [] for name in clearance_utils.list_items("missions")}
    assert data["missions"] == expected


def test_grant_file_clearance_persists(clearance_utils):
    clearance_utils.grant_file_clearance("missions", "Operation Ice Crown", 999)
    data = clearance_utils.load_clearance()
    assert 999 in data["missions"]["Operation Ice Crown"]


def test_revoke_file_clearance_persists(clearance_utils):
    # Ensure the role is initially present
    clearance_utils.grant_file_clearance("missions", "Operation Iron Veil", 888)
    clearance_utils.revoke_file_clearance("missions", "Operation Iron Veil", 888)
    data = clearance_utils.load_clearance()
    assert 888 not in data["missions"]["Operation Iron Veil"]


def test_grant_file_clearance_casts_role_id(clearance_utils):
    clearance_utils.grant_file_clearance("missions", "Operation Ice Crown", "777")
    data = clearance_utils.load_clearance()
    roles = data["missions"]["Operation Ice Crown"]
    assert 777 in roles and "777" not in roles


def test_revoke_file_clearance_casts_role_id(clearance_utils):
    clearance_utils.grant_file_clearance("missions", "Operation Iron Veil", 555)
    clearance_utils.revoke_file_clearance("missions", "Operation Iron Veil", "555")
    data = clearance_utils.load_clearance()
    assert 555 not in data["missions"]["Operation Iron Veil"]


def test_set_files_clearance_updates_multiple_categories(clearance_utils):
    changes = {
        "missions": ["Operation Iron Veil", "Operation Ice Crown"],
        "personnel": ["EXAMPLE PERSONNEL"],
        "intel": ["EXAMPLE INTEL"],
        "fleet": ["EXAMPLE SHIP"],
    }
    clearance_utils.set_files_clearance(changes, [1, 2])
    data = clearance_utils.load_clearance()
    expected = [1, 2]
    assert data["missions"]["Operation Iron Veil"] == expected
    assert data["missions"]["Operation Ice Crown"] == expected
    assert data["personnel"]["EXAMPLE PERSONNEL"] == expected
    assert data["intel"]["EXAMPLE INTEL"] == expected
    assert data["fleet"]["EXAMPLE SHIP"] == expected
