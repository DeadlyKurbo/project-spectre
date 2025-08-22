import importlib
import asyncio

class DummyUser:
    def __init__(self):
        self.id = 1
        self.guild_permissions = type("Perms", (), {"administrator": True})()
    def __str__(self):
        return "dummy"

class DummyGuild:
    owner_id = 1

class DummyResponse:
    def __init__(self):
        self.kwargs = None
    async def send_message(self, *args, **kwargs):
        self.kwargs = kwargs

class DummyChannel:
    async def send(self, *args, **kwargs):
        pass

class DummyInteraction:
    def __init__(self):
        self.user = DummyUser()
        self.guild = DummyGuild()
        self.response = DummyResponse()
        self.channel = DummyChannel()

def test_summon_menu(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    main = importlib.reload(importlib.import_module("main"))
    inter = DummyInteraction()
    logs = []
    async def dummy_log(msg):
        logs.append(msg)
    monkeypatch.setattr(main, "log_action", dummy_log)
    asyncio.run(main.summonmenu_cmd(inter))
    assert inter.response.kwargs["embed"].title == "Project SPECTRE — Black Archives"
    assert isinstance(inter.response.kwargs["view"], main.RootView)
    assert len(logs) == 1
    loop.close()
