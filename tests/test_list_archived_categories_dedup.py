import utils
from pathlib import Path
import pytest

from dossier import list_archived_categories

@pytest.fixture
def util(tmp_path):
    utils.DOSSIERS_DIR = tmp_path / "dossiers"
    utils.CLEARANCE_FILE = tmp_path / "clearance.json"
    return utils

def test_list_archived_categories_dedup(util):
    base = Path(util.DOSSIERS_DIR) / "_archived"
    (base / "Fleet").mkdir(parents=True)
    (base / "fleet").mkdir(parents=True)
    cats = list_archived_categories()
    assert [c.lower() for c in cats] == ["fleet"]
