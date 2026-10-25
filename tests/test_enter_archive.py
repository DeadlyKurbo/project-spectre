import asyncio
import importlib
from types import SimpleNamespace


def test_enter_archive_shows_menu(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    importlib.reload(importlib.import_module("constants"))
    importlib.reload(importlib.import_module("operator_login"))
    views = importlib.reload(importlib.import_module("views"))

    # Avoid background tasks during tests
    monkeypatch.setattr(views.asyncio, "create_task", lambda coro: None)

    captured = {}

    async def send_message(embed=None, view=None, ephemeral=True):
        captured["embed"] = embed
        captured["view"] = view

    class Guild:
        id = 1
        owner_id = 1

        def get_channel(self, _):
            return None

    class Perms:
        administrator = False

    class User:
        id = 1
        roles = []
        guild_permissions = Perms()
        guild = Guild()

    interaction = SimpleNamespace(
        user=User(),
        guild=Guild(),
        response=SimpleNamespace(send_message=send_message),
    )

    async def run():
        rv = views.RootView()
        await rv.open_archive(interaction)

    asyncio.run(run())

    assert captured["embed"] is not None
    assert captured["view"] is not None

