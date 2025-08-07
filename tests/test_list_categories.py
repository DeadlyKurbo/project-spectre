import os
import utils


def test_list_categories_includes_fleet():
    utils.DOSSIERS_DIR = os.path.join(utils.BASE_DIR, "dossiers")
    categories = utils.list_categories()
    assert "fleet" in categories
