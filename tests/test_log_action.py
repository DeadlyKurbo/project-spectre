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


def _load_main(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        main = importlib.reload(importlib.import_module("main"))
    finally:
        asyncio.set_event_loop(None)
        loop.close()
    return main


def test_log_action_fetches_when_not_cached(monkeypatch):
    main = _load_main(monkeypatch)
    channel = DummyChannel()
    bot = DummyBot(channel)
    monkeypatch.setattr(main, "bot", bot)
    monkeypatch.setattr(main, "LOG_CHANNEL_ID", 123)
    asyncio.run(main.log_action("hello"))
    assert channel.messages[0] == "hello"


def test_log_action_silent(monkeypatch):
    main = _load_main(monkeypatch)
    channel = DummyChannel()
    bot = DummyBot(channel)
    monkeypatch.setattr(main, "bot", bot)
    monkeypatch.setattr(main, "LOG_CHANNEL_ID", 123)
    asyncio.run(main.log_action("quiet", broadcast=False))
    assert channel.messages == []
