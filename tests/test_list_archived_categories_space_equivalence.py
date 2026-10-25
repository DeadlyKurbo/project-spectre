from pathlib import Path
import utils
from dossier import list_archived_categories


def test_list_archived_categories_space_equivalence(tmp_path):
    utils.DOSSIERS_DIR = tmp_path
    utils.CLEARANCE_FILE = tmp_path / "clearance.json"
    base = Path(utils.DOSSIERS_DIR) / "_archived"
    (base / "Tech & Equipment").mkdir(parents=True)
    categories = list_archived_categories()
    assert "tech_equipment" in categories
