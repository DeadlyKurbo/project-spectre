import os
import utils
from pathlib import Path
import pytest

os.environ.setdefault("GUILD_ID", "1")
os.environ.setdefault("DISCORD_TOKEN", "test")

from dossier import archive_dossier_file, restore_archived_file


@pytest.fixture
def util(tmp_path):
    utils.DOSSIERS_DIR = tmp_path / "dossiers"
    utils.CLEARANCE_FILE = tmp_path / "clearance.json"
    return utils


def test_archive_and_restore_space_category(util):
    base = Path(util.DOSSIERS_DIR)
    # Create category with spaces in its directory name
    cat_dir = base / "Tech & Equipment"
    cat_dir.mkdir(parents=True)
    file_path = cat_dir / "agent_x.txt"
    file_path.write_text("data")

    archive_dossier_file("tech_equipment", "agent_x")
    archived = base / "_archived" / "Tech & Equipment" / "agent_x.txt"
    assert archived.exists()
    assert not file_path.exists()

    restore_archived_file("tech_equipment", "agent_x")
    assert file_path.exists()
    assert not archived.exists()
