from pathlib import Path

import utils
from dossier import list_archived_categories


def test_list_categories_excludes_internal(tmp_path):
    utils.DOSSIERS_DIR = tmp_path
    utils.CLEARANCE_FILE = tmp_path / "clearance.json"
    base = Path(utils.DOSSIERS_DIR)
    (base / "fleet").mkdir(parents=True)
    (base / "missions").mkdir(parents=True)
    (base / "Backups").mkdir(parents=True)
    (base / "Logs").mkdir(parents=True)
    (base / "Operative Ledger").mkdir(parents=True)
    (base / "Obsidian Vault").mkdir(parents=True)

    categories = utils.list_categories()
    assert categories == ["fleet", "missions"]


def test_list_archived_categories_excludes_internal(tmp_path):
    utils.DOSSIERS_DIR = tmp_path
    utils.CLEARANCE_FILE = tmp_path / "clearance.json"
    base = Path(utils.DOSSIERS_DIR) / "_archived"
    (base / "fleet").mkdir(parents=True)
    (base / "Logs").mkdir(parents=True)
    (base / "Operative Ledger").mkdir(parents=True)

    cats = list_archived_categories()
    assert cats == ["fleet"]

