import pytest

import dossier
import utils
from constants import CATEGORY_ORDER


@pytest.fixture(autouse=True)
def setup(tmp_path):
    utils.DOSSIERS_DIR = tmp_path
    utils.CLEARANCE_FILE = tmp_path / "clearance.json"
    original = CATEGORY_ORDER.copy()
    yield
    CATEGORY_ORDER[:] = original


def test_create_and_reorder_categories(tmp_path):
    dossier.create_category("ops", "Operations")
    assert ("ops", "Operations") in CATEGORY_ORDER

    dossier.reorder_categories(["ops"])
    cats = dossier.list_categories()
    assert cats[0] == "ops"
    # Directory for new category should exist
    assert (tmp_path / "ops").exists()


def test_rename_category(tmp_path):
    dossier.create_category("ops", "Operations")
    dossier.create_dossier_file("ops", "note.txt", "data")
    dossier.rename_category("ops", "logistics", "Logistics")
    assert ("logistics", "Logistics") in CATEGORY_ORDER
    assert (tmp_path / "logistics" / "note.txt").exists()
    assert not (tmp_path / "ops" / "note.txt").exists()


def test_rename_and_move_file(tmp_path):
    # create initial file in existing category
    dossier.create_dossier_file("intel", "agent.txt", "secret")
    orig = tmp_path / "intel" / "agent.txt"
    assert orig.exists()

    # rename within same category
    dossier.rename_dossier_file("intel", "agent", "handler")
    renamed = tmp_path / "intel" / "handler.txt"
    assert renamed.exists()
    assert not orig.exists()

    # create destination category and move file
    dossier.create_category("misc", "Misc")
    dossier.move_dossier_file("intel", "handler", "misc")
    moved = tmp_path / "misc" / "handler.txt"
    assert moved.exists()
    assert not renamed.exists()
