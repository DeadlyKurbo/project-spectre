import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import nextcord

from tasks.remote_config_watcher import RemoteConfigWatcher


class DummyBot:
    def __init__(self):
        self.user = SimpleNamespace(id=999)
        self.guilds = []

    def get_guild(self, gid):
        return None


class DummyGuild:
    def __init__(self, gid: int, channel):
        self.id = gid
        self._channel = channel

    def get_channel(self, channel_id: int):
        if self._channel and self._channel.id == channel_id:
            return self._channel
        return None

    def get_channel_or_thread(self, channel_id: int):
        return self.get_channel(channel_id)


class DummyMessage:
    def __init__(self, mid: int, author_id: int, *, components=True, embeds=True):
        self.id = mid
        self.author = SimpleNamespace(id=author_id)
        self.components = [object()] if components else []
        self.embeds = [object()] if embeds else []


class DummyChannel:
    def __init__(self, cid: int, messages: list[DummyMessage] | None = None):
        self.id = cid
        self._messages = messages or []
        self.last_message_id = self._messages[0].id if self._messages else None

    async def fetch_message(self, message_id: int):
        for message in self._messages:
            if message.id == message_id:
                return message
        response = SimpleNamespace(status=404, reason="not found")
        raise nextcord.NotFound(response=response, message="missing")

    def history(self, limit: int = 5):
        async def iterator():
            count = 0
            for message in self._messages:
                if count >= limit:
                    break
                count += 1
                yield message

        return iterator()


def test_redeploy_when_menu_missing(monkeypatch):
    bot = DummyBot()
    watcher = RemoteConfigWatcher(bot)

    guild = DummyGuild(1, DummyChannel(10))

    monkeypatch.setattr(
        "tasks.remote_config_watcher.read_json",
        lambda key, with_etag=False: ({}, "abc"),
    )
    monkeypatch.setattr(
        "tasks.remote_config_watcher.get_server_config",
        lambda gid: {"MENU_CHANNEL_ID": "10"},
    )

    watcher._last_etag[guild.id] = "abc"
    watcher._menu_missing = AsyncMock(return_value=True)
    watcher._deploy_archive_menu = AsyncMock(return_value="ok")

    asyncio.run(watcher._maybe_redeploy_on_etag_change(guild))

    watcher._deploy_archive_menu.assert_awaited_once_with(guild)


def test_skip_redeploy_when_menu_present(monkeypatch):
    bot = DummyBot()
    watcher = RemoteConfigWatcher(bot)

    guild = DummyGuild(1, DummyChannel(10))

    monkeypatch.setattr(
        "tasks.remote_config_watcher.read_json",
        lambda key, with_etag=False: ({}, "abc"),
    )
    monkeypatch.setattr(
        "tasks.remote_config_watcher.get_server_config",
        lambda gid: {"MENU_CHANNEL_ID": "10"},
    )

    watcher._last_etag[guild.id] = "abc"
    watcher._menu_missing = AsyncMock(return_value=False)
    watcher._deploy_archive_menu = AsyncMock(return_value="ok")

    asyncio.run(watcher._maybe_redeploy_on_etag_change(guild))

    watcher._deploy_archive_menu.assert_not_called()


def test_menu_detection_with_bot_message():
    bot = DummyBot()
    watcher = RemoteConfigWatcher(bot)

    bot_message = DummyMessage(42, bot.user.id)
    channel = DummyChannel(10, [bot_message])
    guild = DummyGuild(1, channel)

    missing = asyncio.run(watcher._menu_missing(guild, 10))
    assert not missing


def test_menu_detection_without_messages():
    bot = DummyBot()
    watcher = RemoteConfigWatcher(bot)

    channel = DummyChannel(10, [])
    guild = DummyGuild(1, channel)

    missing = asyncio.run(watcher._menu_missing(guild, 10))
    assert missing
