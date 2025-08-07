import importlib
import asyncio
from types import SimpleNamespace


def test_category_select_callback(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    main = importlib.reload(importlib.import_module("main"))
    monkeypatch.setattr(main, "load_folder_map", lambda: {"intel": "id1"})

    select = main.CategorySelect()
    select._selected_values = ["intel"]

    class DummyResponse:
        def __init__(self):
            self.sent = None
            self.kwargs = None

        async def send_message(self, content, **kwargs):
            self.sent = content
            self.kwargs = kwargs

    interaction = SimpleNamespace(response=DummyResponse())

    asyncio.run(select.callback(interaction))
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert interaction.response.sent == "You selected `intel`"
    assert interaction.response.kwargs["ephemeral"] is True
    loop.close()

