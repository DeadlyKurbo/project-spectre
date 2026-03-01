import asyncio
import types

import archivist


class DummyMessage:
    def __init__(self, message_id: int, *, author_id: int = 0, has_components: bool = True):
        self.id = message_id
        self.edited = False
        self.deleted = False
        self.author = types.SimpleNamespace(id=author_id)
        self.components = [object()] if has_components else []
        self.embeds = []

    async def edit(self, **kwargs):
        self.edited = True

    async def delete(self):
        self.deleted = True


class DummyChannel:
    def __init__(
        self,
        channel_id: int,
        existing_message: DummyMessage | None = None,
        history_messages: list[DummyMessage] | None = None,
    ):
        self.id = channel_id
        self._existing_message = existing_message
        self._history_messages = history_messages or []
        self.sent_messages: list[DummyMessage] = []

    async def fetch_message(self, message_id: int):
        if self._existing_message and self._existing_message.id == message_id:
            return self._existing_message
        raise RuntimeError("missing")

    async def history(self, *, limit: int = 30):
        for message in self._history_messages[:limit]:
            yield message

    async def send(self, **kwargs):
        message = DummyMessage(9001)
        self.sent_messages.append(message)
        return message


class DummyGuild:
    def __init__(self, guild_id: int, channel: DummyChannel):
        self.id = guild_id
        self._channel = channel
        self._waited_until_ready = 0
        self._added_views = 0
        self._bot_user = types.SimpleNamespace(id=999)
        self._client = types.SimpleNamespace(
            add_view=self._add_view,
            user=self._bot_user,
            wait_until_ready=self._wait_until_ready,
        )
        self._state = types.SimpleNamespace(
            _get_client=lambda: self._client
        )

    async def _wait_until_ready(self):
        self._waited_until_ready += 1

    def _add_view(self, _view):
        self._added_views += 1

    def get_channel(self, channel_id: int):
        if channel_id == self._channel.id:
            return self._channel
        return None

    async def fetch_channel(self, channel_id: int):
        if channel_id == self._channel.id:
            return self._channel
        raise RuntimeError("missing")

    get_channel_or_thread = get_channel


def test_refresh_menus_deletes_previous_anchor_and_reposts(monkeypatch):
    existing = DummyMessage(321, author_id=999)
    stale_menu = DummyMessage(111, author_id=999)
    channel = DummyChannel(77, existing_message=existing, history_messages=[stale_menu])
    guild = DummyGuild(1, channel)

    saved = {}

    monkeypatch.setattr("archivist.invalidate_config", lambda guild_id: None)
    monkeypatch.setattr("archivist.get_server_config", lambda guild_id: {"MENU_CHANNEL_ID": channel.id})
    monkeypatch.setattr("archivist._load_menu_anchor", lambda guild_id: {"channel_id": 77, "message_id": 321})
    monkeypatch.setattr(
        "archivist._save_menu_anchor",
        lambda guild_id, channel_id, message_id: saved.update(
            {"guild_id": guild_id, "channel_id": channel_id, "message_id": message_id}
        ),
    )

    asyncio.run(archivist.refresh_menus(guild))

    assert existing.edited is False
    assert existing.deleted is True
    assert stale_menu.deleted is True
    assert len(channel.sent_messages) == 1
    assert saved == {"guild_id": 1, "channel_id": 77, "message_id": 9001}


def test_refresh_menus_sends_and_persists_when_anchor_missing(monkeypatch):
    channel = DummyChannel(88)
    guild = DummyGuild(2, channel)

    saved = {}

    monkeypatch.setattr("archivist.invalidate_config", lambda guild_id: None)
    monkeypatch.setattr("archivist.get_server_config", lambda guild_id: {"MENU_CHANNEL_ID": channel.id})
    monkeypatch.setattr("archivist._load_menu_anchor", lambda guild_id: {"channel_id": 88, "message_id": 404})
    monkeypatch.setattr(
        "archivist._save_menu_anchor",
        lambda guild_id, channel_id, message_id: saved.update(
            {"guild_id": guild_id, "channel_id": channel_id, "message_id": message_id}
        ),
    )

    asyncio.run(archivist.refresh_menus(guild))

    assert len(channel.sent_messages) == 1
    assert saved == {"guild_id": 2, "channel_id": 88, "message_id": 9001}
    assert guild._waited_until_ready == 1
    assert guild._added_views == 1


def test_refresh_menus_fetches_channel_when_cache_miss(monkeypatch):
    channel = DummyChannel(44)
    guild = DummyGuild(3, channel)
    guild.get_channel = lambda channel_id: None
    guild.get_channel_or_thread = guild.get_channel

    monkeypatch.setattr("archivist.invalidate_config", lambda guild_id: None)
    monkeypatch.setattr("archivist.get_server_config", lambda guild_id: {"MENU_CHANNEL_ID": channel.id})
    monkeypatch.setattr("archivist._load_menu_anchor", lambda guild_id: {})

    asyncio.run(archivist.refresh_menus(guild))

    assert len(channel.sent_messages) == 1
