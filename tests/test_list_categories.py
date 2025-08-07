import utils


def test_list_categories_includes_fleet(tmp_path):
    (tmp_path / "fleet").mkdir()
    utils.DOSSIERS_DIR = str(tmp_path)
    categories = utils.list_categories()
    assert "fleet" in categories
