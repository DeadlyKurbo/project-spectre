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
        self._channels = {channel.id: channel}
        self._bot_user = types.SimpleNamespace(id=999)
        self._state = types.SimpleNamespace(
            _get_client=lambda: types.SimpleNamespace(
                add_view=lambda view: None,
                user=self._bot_user,
            )
        )

    def get_channel(self, channel_id: int):
        return self._channels.get(channel_id)

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


def test_refresh_menus_prefers_configured_channel_and_deletes_old_anchor(monkeypatch):
    old_channel = DummyChannel(88, existing_message=DummyMessage(404, author_id=999))
    configured_channel = DummyChannel(99)
    guild = DummyGuild(3, configured_channel)
    guild._channels[old_channel.id] = old_channel

    saved = {}

    monkeypatch.setattr("archivist.invalidate_config", lambda guild_id: None)
    monkeypatch.setattr("archivist.get_server_config", lambda guild_id: {"MENU_CHANNEL_ID": configured_channel.id})
    monkeypatch.setattr("archivist._load_menu_anchor", lambda guild_id: {"channel_id": old_channel.id, "message_id": 404})
    monkeypatch.setattr(
        "archivist._save_menu_anchor",
        lambda guild_id, channel_id, message_id: saved.update(
            {"guild_id": guild_id, "channel_id": channel_id, "message_id": message_id}
        ),
    )

    asyncio.run(archivist.refresh_menus(guild))

    assert old_channel._existing_message.deleted is True
    assert len(configured_channel.sent_messages) == 1
    assert len(old_channel.sent_messages) == 0
    assert saved == {"guild_id": 3, "channel_id": 99, "message_id": 9001}
