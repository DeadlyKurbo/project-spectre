import importlib
import asyncio
from types import SimpleNamespace


def test_section_zero_command(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")
    monkeypatch.setenv("SECTION_ZERO_CHANNEL_ID", "1")

    sz = importlib.reload(importlib.import_module("section_zero"))
    main = importlib.reload(importlib.import_module("main"))

    class Role:
        def __init__(self, rid):
            self.id = rid

    class Channel:
        id = main.SECTION_ZERO_CHANNEL_ID

    class Perms:
        administrator = False

    class User:
        id = 1
        mention = "<@1>"
        roles = [Role(main.CLASSIFIED_ROLE_ID)]
        guild_permissions = Perms()

    class Response:
        def __init__(self):
            self.kwargs = None

        async def send_message(self, *args, embed=None, view=None, ephemeral=False, content=None):
            if args:
                content = args[0]
            self.kwargs = {
                "embed": embed,
                "view": view,
                "ephemeral": ephemeral,
                "content": content,
            }

    inter = SimpleNamespace(user=User(), channel=Channel(), response=Response())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main.sectionzero_cmd(inter))
    loop.close()
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert isinstance(inter.response.kwargs["view"], sz.SectionZeroControlView)
    assert inter.response.kwargs["embed"].title.startswith("⚫ SECTION ZERO")
