import asyncio
from types import SimpleNamespace

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


def test_category_menu_paginates(monkeypatch):
    def fake_list_items_recursive(category, **_):
        return ["dummy"]

    monkeypatch.setattr(views, "list_items_recursive", fake_list_items_recursive)
    categories = [f"cat{i}" for i in range(30)]
    loop = asyncio.new_event_loop()
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop)
    try:
        menu = CategoryMenu(categories=categories)
        select = next(child for child in menu.children if isinstance(child, nextcord.ui.Select))
        buttons = [child for child in menu.children if isinstance(child, nextcord.ui.Button)]
        assert len(select.options) == 25
        assert len(buttons) == 2
        prev, nxt = buttons
        assert prev.disabled is True
        assert nxt.disabled is False

        captured = {}

        class DummyResponse:
            async def edit_message(self, **kwargs):
                captured.update(kwargs)

        interaction = SimpleNamespace(response=DummyResponse())
        loop.run_until_complete(nxt.callback(interaction))

        assert len(select.options) == 5
        assert select.options[0].value == "cat25"
        assert prev.disabled is False
        assert nxt.disabled is True
        assert "Page 2/2" in select.placeholder
        assert captured.get("view") is menu
    finally:
        loop.close()
