from pathlib import Path
import utils
import pytest

from dossier import list_archived_categories


@pytest.fixture
def util(tmp_path):
    utils.DOSSIERS_DIR = tmp_path
    utils.CLEARANCE_FILE = tmp_path / "clearance.json"
    return utils


def test_list_archived_categories_only_existing(util):
    base = Path(util.DOSSIERS_DIR) / "_archived"
    (base / "fleet").mkdir(parents=True)
    (base / "extra").mkdir(parents=True)
    cats = list_archived_categories()
    assert cats == ["fleet", "extra"]
