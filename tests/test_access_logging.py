import importlib
import asyncio
import json
from types import SimpleNamespace

import utils


def test_log_action_on_file_access(monkeypatch, tmp_path):
    # Set required environment variables for main import
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")

    # Prepare a temporary dossiers directory with one file
    ddir = tmp_path / "intel"
    ddir.mkdir()
    (ddir / "file16.json").write_text(json.dumps({"foo": "bar"}))

    utils.DOSSIERS_DIR = str(tmp_path)
    main = importlib.reload(importlib.import_module("main"))
    main.DOSSIERS_DIR = str(tmp_path)

    import views
    monkeypatch.setattr("views.random.random", lambda: 1.0)

    select = main.CategorySelect()
    select.category = "intel"

    monkeypatch.setattr(main, "get_required_roles", lambda c, i: {1})

    logged = []
    async def fake_log(msg):
        logged.append(msg)
    monkeypatch.setattr(main, "log_action", fake_log)

    class DummyRole:
        def __init__(self, rid):
            self.id = rid
    class Perms:
        administrator = False
    class User:
        id = 42
        roles = [DummyRole(1)]
        guild_permissions = Perms()
        def __str__(self):
            return "member1"
    class Guild:
        owner_id = 99
    class Response:
        async def send_message(self, *a, **k):
            pass
        async def edit_message(self, *a, **k):
            pass

    interaction = SimpleNamespace(
        data={"values": ["file16"]},
        user=User(),
        guild=Guild(),
        response=Response(),
    )

    asyncio.run(select.on_item(interaction))
    asyncio.set_event_loop(asyncio.new_event_loop())
    assert logged == ["📄 member1 accessed `intel/file16.json`."]

