import asyncio
import utils
from storage_spaces import using_root_prefix, save_json
from views import CategoryMenu


def test_section_zero_menu_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "DOSSIERS_DIR", tmp_path)
    with using_root_prefix("section_zero"):
        save_json("redaction_matrix/test.json", {"content": "ok"})
    async def run():
        menu = CategoryMenu(categories=["redaction_matrix"], root_prefix="section_zero")
        opt = menu.children[0].options[0]
        return opt.description
    desc = asyncio.run(run())
    assert desc == "1 file(s)"
