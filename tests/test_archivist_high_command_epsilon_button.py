import asyncio
import importlib
from types import SimpleNamespace


def test_epsilon_button_triggers_protocol(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")

    arch = importlib.reload(importlib.import_module("archivist"))
    main = importlib.reload(importlib.import_module("main"))

    called = {}

    async def fake_protocol_epsilon(interaction):
        called["interaction"] = interaction

    monkeypatch.setattr(main, "protocol_epsilon", fake_protocol_epsilon)

    async def run_test():
        user = SimpleNamespace()
        console = arch.HighCommandConsoleView(user)
        actions = arch.HighCommandActionsView(console)

        epsilon_button = None
        for child in actions.children:
            if getattr(child, "label", "") == " Protocol Epsilon":
                epsilon_button = child
                break

        assert epsilon_button is not None

        inter = SimpleNamespace()
        await epsilon_button.callback(inter)
        return inter

    loop = asyncio.new_event_loop()
    inter = loop.run_until_complete(run_test())
    loop.close()

    assert called["interaction"] is inter

