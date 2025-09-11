from pathlib import Path

import utils


def test_list_categories_excludes_section_zero(tmp_path):
    """Section Zero categories should not appear in the public archive."""

    utils.DOSSIERS_DIR = tmp_path
    utils.CLEARANCE_FILE = tmp_path / "clearance.json"

    base = Path(utils.DOSSIERS_DIR)
    (base / "missions").mkdir(parents=True)
    (base / "backups").mkdir(parents=True)
    (base / "logs").mkdir(parents=True)

    categories = utils.list_categories()
    assert categories == ["missions"]
