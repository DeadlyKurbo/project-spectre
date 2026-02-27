import asyncio
import types

import archivist


class DummyMessage:
    def __init__(self, message_id: int):
        self.id = message_id
        self.edited = False

    async def edit(self, **kwargs):
        self.edited = True


class DummyChannel:
    def __init__(self, channel_id: int, existing_message: DummyMessage | None = None):
        self.id = channel_id
        self._existing_message = existing_message
        self.sent_messages: list[DummyMessage] = []
        self.purged = False

    async def fetch_message(self, message_id: int):
        if self._existing_message and self._existing_message.id == message_id:
            return self._existing_message
        raise RuntimeError("missing")

    async def purge(self):
        self.purged = True

    async def send(self, **kwargs):
        message = DummyMessage(9001)
        self.sent_messages.append(message)
        return message


class DummyGuild:
    def __init__(self, guild_id: int, channel: DummyChannel):
        self.id = guild_id
        self._channel = channel
        self._state = types.SimpleNamespace(
            _get_client=lambda: types.SimpleNamespace(add_view=lambda view: None)
        )

    def get_channel(self, channel_id: int):
        if channel_id == self._channel.id:
            return self._channel
        return None

    get_channel_or_thread = get_channel


def test_refresh_menus_purges_and_reposts_even_with_existing_anchor(monkeypatch):
    existing = DummyMessage(321)
    channel = DummyChannel(77, existing_message=existing)
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
    assert channel.purged is True
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

    assert channel.purged is True
    assert len(channel.sent_messages) == 1
    assert saved == {"guild_id": 2, "channel_id": 88, "message_id": 9001}
