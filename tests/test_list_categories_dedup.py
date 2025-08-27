import utils
from pathlib import Path
import pytest

@pytest.fixture
def util(tmp_path):
    utils.DOSSIERS_DIR = tmp_path / "dossiers"
    utils.CLEARANCE_FILE = tmp_path / "clearance.json"
    return utils


def test_list_categories_dedup(util):
    base = Path(util.DOSSIERS_DIR)
    (base / "Fleet").mkdir(parents=True)
    (base / "fleet").mkdir(parents=True)
    cats = [c.lower() for c in util.list_categories()]
    assert cats.count("fleet") == 1
