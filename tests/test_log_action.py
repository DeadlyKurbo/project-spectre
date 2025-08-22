import importlib
import asyncio

class DummyChannel:
    def __init__(self):
        self.messages = []
    async def send(self, msg):
        self.messages.append(msg)

class DummyBot:
    def __init__(self, channel):
        self._channel = channel
    def get_channel(self, cid):
        return None
    async def fetch_channel(self, cid):
        return self._channel

def test_log_action_fetches_when_not_cached(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")
    main = importlib.reload(importlib.import_module("main"))
    channel = DummyChannel()
    bot = DummyBot(channel)
    monkeypatch.setattr(main, "bot", bot)
    monkeypatch.setattr(main, "LOG_CHANNEL_ID", 123)
    asyncio.run(main.log_action("hello"))
    assert channel.messages == ["hello"]
