from pathlib import Path

import utils
from constants import CATEGORY_ORDER


def test_list_categories_include_canonical(tmp_path):
    utils.DOSSIERS_DIR = tmp_path
    utils.CLEARANCE_FILE = tmp_path / "clearance.json"
    base = Path(utils.DOSSIERS_DIR)
    (base / "fleet").mkdir(parents=True)
    (base / "extra").mkdir(parents=True)
    categories = utils.list_categories()
    expected = [slug for slug, _label in CATEGORY_ORDER]
    assert categories[: len(expected)] == expected
    assert "extra" in categories
