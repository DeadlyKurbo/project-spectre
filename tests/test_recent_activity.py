import os
import asyncio
import importlib
import utils
from storage_spaces import save_text

os.environ.setdefault("DISCORD_TOKEN", "x")
os.environ.setdefault("GUILD_ID", "1")
os.environ.setdefault("MENU_CHANNEL_ID", "1")


class DummyUser:
    id = 1
    guild_permissions = type("Perms", (), {"administrator": True})()
    roles = []
    mention = "<@1>"


class DummyResponse:
    def __init__(self):
        self.kwargs = None

    async def send_message(self, *args, **kwargs):
        self.kwargs = kwargs


class DummyInteraction:
    def __init__(self):
        self.user = DummyUser()
        self.response = DummyResponse()


def test_open_recent_activity(monkeypatch, tmp_path):
    utils.DOSSIERS_DIR = tmp_path / "dossiers"
    os.makedirs(utils.DOSSIERS_DIR, exist_ok=True)
    save_text(
        "logs/actions.log",
        "\n".join(
            [
                "2024-01-01T00:00:00 🚨 bob filed ARCHIVIST incident 'foo': bar",
                "2024-01-01T00:00:01 📄 alice accessed `intel/file`.",
            ]
        ),
    )
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    importlib.reload(importlib.import_module("main"))
    arch = importlib.reload(importlib.import_module("archivist"))

    async def run_test():
        view = arch.ArchivistConsoleView(DummyUser())
        inter = DummyInteraction()
        await view.open_recent(inter)
        return inter

    inter = loop.run_until_complete(run_test())
    desc = inter.response.kwargs["embed"].description
    assert "intel/file" in desc
    assert "incident" not in desc
    loop.close()
