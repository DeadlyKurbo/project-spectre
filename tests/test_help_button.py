import asyncio
import importlib
from types import SimpleNamespace


def test_help_button_opens_modal(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    views = importlib.reload(importlib.import_module("views"))
    archivist = importlib.reload(importlib.import_module("archivist"))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def build_view():
        return views.RootView()

    rv = loop.run_until_complete(build_view())
    labels = [child.label for child in rv.children]
    assert "Help" in labels

    captured = {}

    async def send_modal(modal):
        captured["modal"] = modal

    interaction = SimpleNamespace(
        user=SimpleNamespace(id=1),
        response=SimpleNamespace(send_modal=send_modal),
    )

    loop.run_until_complete(rv.open_help(interaction))
    loop.close()
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert "modal" in captured
    assert isinstance(captured["modal"], archivist.ReportProblemModal)
