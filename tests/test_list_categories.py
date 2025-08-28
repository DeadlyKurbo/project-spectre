from pathlib import Path
import utils


def test_list_categories_only_existing(tmp_path):
    utils.DOSSIERS_DIR = tmp_path
    utils.CLEARANCE_FILE = tmp_path / "clearance.json"
    base = Path(utils.DOSSIERS_DIR)
    (base / "fleet").mkdir(parents=True)
    (base / "extra").mkdir(parents=True)
    categories = utils.list_categories()
    assert categories == ["fleet", "extra"]
