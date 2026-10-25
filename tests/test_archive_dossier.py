import os
import utils
from pathlib import Path
import pytest

os.environ.setdefault("GUILD_ID", "1")
os.environ.setdefault("DISCORD_TOKEN", "test")

from dossier import create_dossier_file, archive_dossier_file


@pytest.fixture
def util(tmp_path):
    utils.DOSSIERS_DIR = tmp_path / "dossiers"
    utils.CLEARANCE_FILE = tmp_path / "clearance.json"
    return utils


def test_archive_dossier_file(util):
    create_dossier_file("intel", "agent_x", "{}")
    orig = Path(util.DOSSIERS_DIR) / "intel" / "agent_x.txt"
    assert orig.exists()
    archive_dossier_file("intel", "agent_x")
    archived = Path(util.DOSSIERS_DIR) / "_archived" / "intel" / "agent_x.txt"
    assert archived.exists()
    assert not orig.exists()
