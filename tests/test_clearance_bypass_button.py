import importlib
import asyncio
from types import SimpleNamespace


def test_bypass_requires_classified_role(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    importlib.reload(importlib.import_module("constants"))
    importlib.reload(importlib.import_module("operator_login"))
    views = importlib.reload(importlib.import_module("views"))

    # Prevent background task scheduling during tests
    monkeypatch.setattr(views.asyncio, "create_task", lambda coro: None)

    class DummyMember:
        id = 1
        roles = []

    captured = {}

    async def dummy_send_message(content=None, **kwargs):
        captured["content"] = content

    interaction = SimpleNamespace(
        user=DummyMember(),
        response=SimpleNamespace(send_message=dummy_send_message),
    )

    async def run_test():
        view = views.RootView()
        await view.handle_bypass(interaction)

    asyncio.run(run_test())

    assert "Classified clearance required" in captured.get("content", "")

