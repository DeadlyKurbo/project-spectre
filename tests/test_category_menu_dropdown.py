import asyncio
import nextcord
import views
from views import CategoryMenu


def test_category_menu_uses_dropdown(monkeypatch):
    def fake_list_items_recursive(category):
        return ["dummy"]

    monkeypatch.setattr(views, "list_items_recursive", fake_list_items_recursive)
    loop = asyncio.new_event_loop()
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop)
    try:
        menu = CategoryMenu(categories=["personnel", "missions"])
    finally:
        loop.close()
    assert len(menu.children) == 1
    select = menu.children[0]
    assert isinstance(select, nextcord.ui.Select)
    labels = [opt.label for opt in select.options]
    emojis = [str(opt.emoji) for opt in select.options]
    assert "Personnel" in labels
    assert "Missions" in labels
    assert "👥" in emojis
    assert "🎯" in emojis
