import asyncio
import importlib
from types import SimpleNamespace


def _reset_loop(loop):
    loop.close()
    asyncio.set_event_loop(asyncio.new_event_loop())


def test_dispatch_without_context():
    module = importlib.reload(importlib.import_module("spectre.commands.archivist"))

    class Response:
        def __init__(self):
            self.kwargs = None

        async def send_message(self, content, *, ephemeral=False):
            self.kwargs = {"content": content, "ephemeral": ephemeral}

    interaction = SimpleNamespace(response=Response())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(module.dispatch_archivist_console(interaction))
    assert interaction.response.kwargs == {
        "content": " Archivist console temporarily unavailable. Please try again.",
        "ephemeral": True,
    }
    _reset_loop(loop)


def test_dispatch_with_context(monkeypatch):
    module = importlib.reload(importlib.import_module("spectre.commands.archivist"))

    called = {}

    async def fake_open(context, interaction):
        called["context"] = context
        called["interaction"] = interaction

    monkeypatch.setattr(module, "open_archivist_console", fake_open)
    module._active_context = "ctx"

    interaction = SimpleNamespace(response=SimpleNamespace())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(module.dispatch_archivist_console(interaction))
    assert called == {"context": "ctx", "interaction": interaction}
    _reset_loop(loop)


def test_root_view_archivist_button(monkeypatch):
    module = importlib.reload(importlib.import_module("spectre.commands.archivist"))

    async def fake_dispatch(interaction):
        fake_dispatch.called = interaction

    monkeypatch.setattr(module, "dispatch_archivist_console", fake_dispatch)
    import views

    view = views.RootView()
    interaction = SimpleNamespace()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(view.open_archivist_menu(interaction))
    assert fake_dispatch.called is interaction
    _reset_loop(loop)
