import asyncio
import json
import pytest

import dossier
import utils
from constants import CATEGORY_ORDER, CATEGORY_STYLES
from views import CategoryButton, _color_to_style


@pytest.fixture(autouse=True)
def setup(tmp_path):
    utils.DOSSIERS_DIR = tmp_path
    utils.CLEARANCE_FILE = tmp_path / "clearance.json"
    original_order = CATEGORY_ORDER.copy()
    original_styles = CATEGORY_STYLES.copy()
    yield
    CATEGORY_ORDER[:] = original_order
    CATEGORY_STYLES.clear()
    CATEGORY_STYLES.update(original_styles)


def test_create_and_reorder_categories(tmp_path):
    dossier.create_category("ops", "Operations", emoji="⚔️", color="0x112233")
    assert ("ops", "Operations") in CATEGORY_ORDER
    assert CATEGORY_STYLES["ops"] == ("⚔️", 0x112233)

    # Category button and menu should reflect configured style
    btn = CategoryButton("ops")
    assert btn.label == "Operations"
    assert (str(btn.emoji) if btn.emoji else "") == "⚔️"
    assert btn.style == _color_to_style(0x112233)
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        async def _run():
            return btn.build_item_list_view()
        embed, _view = loop.run_until_complete(_run())
    finally:
        loop.close()
    assert embed.color.value == 0x112233

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


def test_update_category_style(tmp_path):
    dossier.create_category("ops", "Operations", emoji="⚔️", color="0x112233")
    dossier.update_category_style("ops", emoji="🛠️", color="0x445566")
    assert CATEGORY_STYLES["ops"] == ("🛠️", 0x445566)

    btn = CategoryButton("ops")
    assert (str(btn.emoji) if btn.emoji else "") == "🛠️"
    assert btn.style == _color_to_style(0x445566)


def test_category_manifest_persisted(tmp_path):
    utils.DOSSIERS_DIR = tmp_path
    utils.CLEARANCE_FILE = tmp_path / "clearance.json"
    dossier.create_category("ops", "Operations")
    manifest = tmp_path / "config" / "categories.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text())
    slugs = [entry.get("slug") for entry in data.get("categories", []) if isinstance(entry, dict)]
    assert "ops" in slugs
