import importlib
import asyncio
from types import SimpleNamespace


def _setup(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    importlib.reload(importlib.import_module("constants"))
    importlib.reload(importlib.import_module("operator_login"))
    views = importlib.reload(importlib.import_module("views"))
    # Avoid scheduling background tasks during tests
    monkeypatch.setattr(views.asyncio, "create_task", lambda coro: None)
    return views


def _dummy_interaction():
    class Perms:
        administrator = False

    class Guild:
        owner_id = 2

    class User:
        id = 1
        roles = []
        guild_permissions = Perms()
        guild = Guild()

    captured = {}

    async def send_message(content=None, **_):
        captured["content"] = content

    inter = SimpleNamespace(user=User(), response=SimpleNamespace(send_message=send_message))
    return inter, captured


def test_lock_blocks_enter_archive(monkeypatch, tmp_path):
    views = _setup(monkeypatch, tmp_path)
    arch = importlib.reload(importlib.import_module("archivist"))
    arch.lock_archive()

    rv = views.RootView()
    inter, captured = _dummy_interaction()
    asyncio.run(rv.open_archive(inter))

    assert captured.get("content") == " Archive access locked."

