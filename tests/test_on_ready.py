import importlib
import asyncio

class DummyChannel:
    def __init__(self):
        self.kwargs = None
    async def send(self, *args, **kwargs):
        self.kwargs = kwargs

class DummyBot:
    def __init__(self, channel):
        self.user = "dummy"
        self.synced = False
        self._channel = channel
    async def sync_application_commands(self):
        self.synced = True
    def get_channel(self, cid):
        return self._channel


def test_on_ready_syncs_and_posts_menu(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    main = importlib.reload(importlib.import_module("main"))

    channel = DummyChannel()
    bot = DummyBot(channel)
    monkeypatch.setattr(main, "bot", bot)

    asyncio.run(main.on_ready())

    assert bot.synced
    assert channel.kwargs["embed"].title == "Project SPECTRE File Explorer"
    assert isinstance(channel.kwargs["view"], main.RootView)
    loop.close()
