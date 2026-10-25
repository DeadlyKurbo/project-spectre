import importlib, asyncio
from types import SimpleNamespace

import utils
from constants import PAGE_SEPARATOR


def test_show_item_respects_page_separator(monkeypatch, tmp_path):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")

    ddir = tmp_path / "intel"
    ddir.mkdir()
    text = PAGE_SEPARATOR.join(["p1", "p2", "p3"])
    (ddir / "file1.txt").write_text(text)

    utils.DOSSIERS_DIR = str(tmp_path)
    main = importlib.reload(importlib.import_module("main"))
    main.DOSSIERS_DIR = str(tmp_path)

    import views
    monkeypatch.setattr(views, "random", SimpleNamespace(random=lambda: 1.0))
    monkeypatch.setattr(views, "check_temp_clearance", lambda *a, **k: False)
    monkeypatch.setattr(main, "get_required_roles", lambda c, i: {1})

    async def _no_log(msg):
        return None

    monkeypatch.setattr(main, "log_action", _no_log)

    select = main.CategorySelect()
    select.category = "intel"

    class Perms:
        administrator = False

    class Role:
        def __init__(self, rid):
            self.id = rid

    class User:
        id = 42
        roles = [Role(1)]
        guild_permissions = Perms()
        mention = "<@42>"

    class Guild:
        owner_id = 99

    class Response:
        def __init__(self):
            self.kwargs = None

        async def edit_message(self, *a, **k):
            self.kwargs = k

        async def send_message(self, *a, **k):
            self.kwargs = k

    class Followup:
        async def send(self, *a, **k):
            pass

    interaction = SimpleNamespace(
        user=User(),
        guild=Guild(),
        response=Response(),
        followup=Followup(),
    )

    asyncio.run(select._show_item(interaction, "file1"))
    asyncio.set_event_loop(asyncio.new_event_loop())

    embed = interaction.response.kwargs["embed"]
    view = interaction.response.kwargs["view"]
    assert embed.fields[1].name == "Contents (page 1/3)"
    assert "p1" in embed.fields[1].value

    next_btn = next(
        item for item in view.children if getattr(item, "custom_id", "") == "next_page_v1"
    )
    inter2 = SimpleNamespace(response=Response())
    asyncio.run(next_btn.callback(inter2))
    asyncio.set_event_loop(asyncio.new_event_loop())

    embed2 = inter2.response.kwargs["embed"]
    assert embed2.fields[1].name == "Contents (page 2/3)"
    assert "p2" in embed2.fields[1].value

