"""Restarts used to leave two archive menus: concurrent deploys raced each other."""

from __future__ import annotations

import asyncio
import itertools
import types
from unittest.mock import AsyncMock

import archivist
from tasks import deploy_queue
from tasks.remote_config_watcher import RemoteConfigWatcher

BOT_ID = 999


class LiveMessage:
    def __init__(self, channel: "LiveChannel", message_id: int):
        self.id = message_id
        self.author = types.SimpleNamespace(id=BOT_ID)
        self.components = [object()]
        self.embeds = []
        self._channel = channel

    async def delete(self):
        await asyncio.sleep(0)  # network round trip
        self._channel.messages = [m for m in self._channel.messages if m.id != self.id]


class LiveChannel:
    """Channel that behaves like Discord: messages persist until deleted."""

    def __init__(self, channel_id: int):
        self.id = channel_id
        self.messages: list[LiveMessage] = []
        self._ids = itertools.count(1000)

    async def fetch_message(self, message_id: int):
        await asyncio.sleep(0)
        for message in self.messages:
            if message.id == message_id:
                return message
        raise RuntimeError("not found")

    async def history(self, *, limit: int = 30):
        for message in list(reversed(self.messages))[:limit]:
            await asyncio.sleep(0)
            yield message

    async def send(self, **_kwargs):
        await asyncio.sleep(0)
        message = LiveMessage(self, next(self._ids))
        self.messages.append(message)
        return message


class LiveGuild:
    def __init__(self, guild_id: int, channel: LiveChannel):
        self.id = guild_id
        self._channel = channel
        client = types.SimpleNamespace(add_view=lambda view: None, user=types.SimpleNamespace(id=BOT_ID))
        self._state = types.SimpleNamespace(_get_client=lambda: client)

    def get_channel(self, channel_id: int):
        return self._channel if channel_id == self._channel.id else None

    get_channel_or_thread = get_channel


def _patch_storage(monkeypatch, channel: LiveChannel) -> dict:
    anchors: dict[int, dict] = {}
    monkeypatch.setattr(archivist, "invalidate_config", lambda guild_id: None)
    monkeypatch.setattr(archivist, "get_server_config", lambda guild_id: {"MENU_CHANNEL_ID": channel.id})
    monkeypatch.setattr(archivist, "_load_menu_anchor", lambda guild_id: dict(anchors[guild_id]) if guild_id in anchors else None)
    monkeypatch.setattr(
        archivist,
        "_save_menu_anchor",
        lambda guild_id, channel_id, message_id: anchors.__setitem__(
            guild_id, {"channel_id": channel_id, "message_id": message_id}
        ),
    )
    monkeypatch.setattr(archivist, "_MENU_REFRESH_LOCKS", {})
    return anchors


def test_concurrent_menu_refreshes_leave_a_single_menu(monkeypatch):
    channel = LiveChannel(77)
    guild = LiveGuild(1, channel)
    anchors = _patch_storage(monkeypatch, channel)

    async def scenario():
        # Menu left behind by the previous process.
        await archivist.refresh_menus(guild)
        assert len(channel.messages) == 1
        # Restart: on_ready, the config watcher and the deploy queue all fire together.
        results = await asyncio.gather(*(archivist.refresh_menus(guild) for _ in range(3)))
        return results

    results = asyncio.run(scenario())

    assert all(results)
    assert len(channel.messages) == 1
    assert anchors[1]["message_id"] == channel.messages[0].id


def test_config_watcher_first_poll_does_not_redeploy_existing_menu(monkeypatch):
    watcher = RemoteConfigWatcher(types.SimpleNamespace(user=types.SimpleNamespace(id=BOT_ID)))
    guild = types.SimpleNamespace(id=1)
    monkeypatch.setattr("tasks.remote_config_watcher.read_json", lambda key, with_etag=False: ({}, "etag-1"))
    monkeypatch.setattr("tasks.remote_config_watcher.get_server_config", lambda gid: {"MENU_CHANNEL_ID": "10"})
    watcher._menu_missing = AsyncMock(return_value=False)
    watcher._deploy_archive_menu = AsyncMock(return_value="ok")

    asyncio.run(watcher._maybe_redeploy_on_etag_change(guild))

    watcher._deploy_archive_menu.assert_not_called()
    assert watcher._last_etag[1] == "etag-1"


def test_config_watcher_redeploys_after_config_change(monkeypatch):
    watcher = RemoteConfigWatcher(types.SimpleNamespace(user=types.SimpleNamespace(id=BOT_ID)))
    guild = types.SimpleNamespace(id=1)
    watcher._last_etag[1] = "etag-1"
    monkeypatch.setattr("tasks.remote_config_watcher.read_json", lambda key, with_etag=False: ({}, "etag-2"))
    monkeypatch.setattr("tasks.remote_config_watcher.get_server_config", lambda gid: {"MENU_CHANNEL_ID": "10"})
    watcher._menu_missing = AsyncMock(return_value=False)
    watcher._deploy_archive_menu = AsyncMock(return_value="ok")

    asyncio.run(watcher._maybe_redeploy_on_etag_change(guild))

    watcher._deploy_archive_menu.assert_awaited_once_with(guild)


def test_config_watcher_without_config_doc_does_not_redeploy_every_poll(monkeypatch):
    watcher = RemoteConfigWatcher(types.SimpleNamespace(user=types.SimpleNamespace(id=BOT_ID)))
    guild = types.SimpleNamespace(id=1)
    monkeypatch.setattr("tasks.remote_config_watcher.read_json", lambda key, with_etag=False: (None, None))
    monkeypatch.setattr("tasks.remote_config_watcher.get_server_config", lambda gid: {"MENU_CHANNEL_ID": "10"})
    watcher._menu_missing = AsyncMock(return_value=False)
    watcher._deploy_archive_menu = AsyncMock(return_value="ok")

    for _ in range(3):
        asyncio.run(watcher._maybe_redeploy_on_etag_change(guild))

    watcher._deploy_archive_menu.assert_not_called()


def test_deploy_queue_is_consumed_by_one_watcher_at_a_time(monkeypatch):
    calls = []

    async def slow_consume(_bot):
        calls.append("start")
        await asyncio.sleep(0.01)

    monkeypatch.setattr(deploy_queue, "_consume_deploy_queue", slow_consume)
    monkeypatch.setattr(deploy_queue, "_QUEUE_LOCK", asyncio.Lock())

    async def scenario():
        await asyncio.gather(
            deploy_queue.consume_deploy_queue(object()),
            deploy_queue.consume_deploy_queue(object()),
        )

    asyncio.run(scenario())

    assert calls == ["start"]
