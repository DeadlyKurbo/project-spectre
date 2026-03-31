import asyncio
import importlib
import pytest


class DummyUser:
    mention = "<@1>"


class DummyChannel:
    def __init__(self, cid: int):
        self.id = cid
        self.sent = []
        self.guild = None
        self.purged = False

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))

    async def purge(self):
        self.purged = True
        self.sent.clear()


class DummyGuild:
    def __init__(self, menu_ch, gid=1):
        self.id = gid
        self._channels = {menu_ch.id: menu_ch}
        menu_ch.guild = self

    def get_channel(self, cid: int):
        return self._channels.get(cid)

    def get_role(self, rid: int):
        return None


class DummyResponse:
    def __init__(self):
        self.kwargs = None

    async def send_message(self, *args, **kwargs):
        self.kwargs = kwargs


class DummyInteraction:
    def __init__(self, guild):
        self.user = DummyUser()
        self.guild = guild
        self.response = DummyResponse()


@pytest.mark.parametrize(
    "view_cls_name",
    ["ArchivistConsoleView", "ArchivistLimitedConsoleView"],
)
def test_summon_all_menus_button(monkeypatch, view_cls_name):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    import constants
    importlib.reload(constants)
    server_config = importlib.reload(importlib.import_module("server_config"))
    main = importlib.reload(importlib.import_module("main"))
    arch = importlib.reload(importlib.import_module("archivist"))

    menu_ch = DummyChannel(1)
    guild = DummyGuild(menu_ch)
    inter = DummyInteraction(guild)

    logs = []

    async def dummy_log(msg, guild_id=None):
        _ = guild_id
        logs.append(msg)

    monkeypatch.setattr(main, "log_action", dummy_log)

    async def run_test():
        view_cls = getattr(arch, view_cls_name)
        view = view_cls(inter.user)
        await view.summon_menus(inter)

    loop.run_until_complete(run_test())

    assert menu_ch.sent
    assert menu_ch.sent[0][1]["embed"].title == "SPECTRE Archive Console"
    assert "summoned all menus" in logs[0]

    loop.close()

