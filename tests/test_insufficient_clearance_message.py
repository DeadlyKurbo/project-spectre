import importlib
import asyncio
import json
from types import SimpleNamespace

import utils


def test_insufficient_clearance_message(monkeypatch, tmp_path):
    # Environment variables required for importing main
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")

    # Prepare temporary dossier file
    ddir = tmp_path / "intel"
    ddir.mkdir()
    (ddir / "file16.json").write_text(json.dumps({"foo": "bar"}))

    utils.DOSSIERS_DIR = str(tmp_path)
    main = importlib.reload(importlib.import_module("main"))
    main.DOSSIERS_DIR = str(tmp_path)

    select = main.CategorySelect()
    select.category = "intel"

    # File requires Level 3 or Level 5 clearance
    monkeypatch.setattr(
        main,
        "get_required_roles",
        lambda c, i: {main.LEVEL3_ROLE_ID, main.LEVEL5_ROLE_ID},
    )

    # Capture log entries without performing real logging
    async def fake_log(msg):
        pass
    monkeypatch.setattr(main, "log_action", fake_log)

    class DummyRole:
        def __init__(self, rid, name):
            self.id = rid
            self.name = name

    role_map = {
        main.LEVEL3_ROLE_ID: DummyRole(main.LEVEL3_ROLE_ID, "Level 3 – Officer"),
        main.LEVEL5_ROLE_ID: DummyRole(main.LEVEL5_ROLE_ID, "Level 5 – Director"),
    }

    class Guild:
        owner_id = 99
        def get_role(self, rid):
            return role_map.get(rid)

    class Perms:
        administrator = False

    class User:
        id = 42
        roles = []
        guild_permissions = Perms()
        def __str__(self):
            return "member1"

    class Response:
        def __init__(self):
            self.sent = []
        async def send_message(self, content, *a, **k):
            self.sent.append(content)
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

    assert interaction.response.sent == [
        "⛔ You need at least Level 3 – Officer clearance for this file."
    ]

