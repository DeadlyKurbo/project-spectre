import utils
from pathlib import Path


def test_list_categories_hyphen_equivalence(tmp_path):
    utils.DOSSIERS_DIR = tmp_path
    utils.CLEARANCE_FILE = tmp_path / "clearance.json"
    base = Path(utils.DOSSIERS_DIR)
    (base / "active-efforts").mkdir(parents=True)
    categories = utils.list_categories()
    assert "active_efforts" in categories
