import utils
from pathlib import Path
import pytest


@pytest.fixture
def util(tmp_path):
    utils.DOSSIERS_DIR = tmp_path / "dossiers"
    utils.CLEARANCE_FILE = tmp_path / "clearance.json"
    return utils


def test_remove_dossier_file(util):
    util.create_dossier_file("intel", "agent_x", "{}")
    util.grant_file_clearance("intel", "agent_x", 123)
    path = Path(util.DOSSIERS_DIR) / "intel" / "agent_x.json"
    assert path.exists()
    util.remove_dossier_file("intel", "agent_x")
    assert not path.exists()
    assert "agent_x" not in util.load_clearance().get("intel", {})
