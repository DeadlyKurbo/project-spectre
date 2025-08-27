import utils
import pytest

from dossier import list_archived_categories
from constants import CATEGORY_ORDER


@pytest.fixture
def util(tmp_path):
    utils.DOSSIERS_DIR = tmp_path / "dossiers"
    utils.CLEARANCE_FILE = tmp_path / "clearance.json"
    return utils


def test_list_archived_categories_includes_configured(util):
    cats = list_archived_categories()
    configured = [slug for slug, _ in CATEGORY_ORDER]
    for slug in configured:
        assert slug in cats
