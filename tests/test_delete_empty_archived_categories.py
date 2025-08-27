import utils
from storage_spaces import ensure_dir, save_text
from dossier import delete_empty_archived_categories, list_archived_categories
from constants import ROOT_PREFIX


def test_delete_empty_archived_categories(tmp_path):
    utils.DOSSIERS_DIR = tmp_path / "dossiers"
    utils.CLEARANCE_FILE = tmp_path / "clearance.json"
    ensure_dir(f"{ROOT_PREFIX}/_archived/alpha")
    ensure_dir(f"{ROOT_PREFIX}/_archived/beta")
    save_text(f"{ROOT_PREFIX}/_archived/beta/file.txt", "x")
    removed = delete_empty_archived_categories()
    assert removed == ["alpha"]
    assert list_archived_categories() == ["beta"]
