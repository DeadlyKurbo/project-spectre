import types

import asyncio

from spectre.context import SpectreContext


class DummyLazarus:
    pass


class DummyChannel:
    def __init__(self):
        self.messages = []

    async def send(self, message=None, *, embed=None):
        self.messages.append({"message": message, "embed": embed})


class DummyBot:
    def __init__(self):
        self.guilds = []
        self._channels = {}

    def get_channel(self, channel_id):
        return self._channels.get(channel_id)

    async def fetch_channel(self, channel_id):
        return self._channels.get(channel_id)


def test_log_action_broadcasts_to_admin_log_channel(monkeypatch):
    bot = DummyBot()
    channel = DummyChannel()
    bot._channels[555] = channel

    context = SpectreContext(
        bot=bot,
        settings=None,  # type: ignore[arg-type]
        logger=types.SimpleNamespace(info=lambda *a, **k: None, debug=lambda *a, **k: None, warning=lambda *a, **k: None),
        lazarus_ai=DummyLazarus(),
        guild_ids=[42],
    )

    monkeypatch.setattr("spectre.context.get_server_config", lambda _gid: {"ADMIN_LOG_CHANNEL_ID": 555})
    monkeypatch.setattr("spectre.context.get_dashboard_logging_channels", lambda _gid: {})

    asyncio.run(context.log_action("Test admin message"))

    assert len(channel.messages) == 1
    payload = channel.messages[0]
    assert payload["message"] is None
    assert payload["embed"].title == "INTELLIGENCE ACCESS"
    assert payload["embed"].fields[1].value == "Test admin message"


def test_log_action_skips_channel_publish_when_broadcast_disabled(monkeypatch):
    bot = DummyBot()
    channel = DummyChannel()
    bot._channels[555] = channel

    context = SpectreContext(
        bot=bot,
        settings=None,  # type: ignore[arg-type]
        logger=types.SimpleNamespace(info=lambda *a, **k: None, debug=lambda *a, **k: None, warning=lambda *a, **k: None),
        lazarus_ai=DummyLazarus(),
        guild_ids=[42],
    )

    monkeypatch.setattr("spectre.context.get_server_config", lambda _gid: {"ADMIN_LOG_CHANNEL_ID": 555})
    monkeypatch.setattr("spectre.context.get_dashboard_logging_channels", lambda _gid: {})

    asyncio.run(context.log_action("No broadcast", broadcast=False))

    assert channel.messages == []


def test_log_action_renders_security_breach_embed(monkeypatch):
    bot = DummyBot()
    channel = DummyChannel()
    bot._channels[555] = channel

    context = SpectreContext(
        bot=bot,
        settings=None,  # type: ignore[arg-type]
        logger=types.SimpleNamespace(info=lambda *a, **k: None, debug=lambda *a, **k: None, warning=lambda *a, **k: None),
        lazarus_ai=DummyLazarus(),
        guild_ids=[42],
    )

    monkeypatch.setattr("spectre.context.get_server_config", lambda _gid: {"ADMIN_LOG_CHANNEL_ID": 555})
    monkeypatch.setattr("spectre.context.get_dashboard_logging_channels", lambda _gid: {})

    asyncio.run(
        context.log_action("Unauthorized attempt by @Surikacrack to access personnel/The_Director.txt")
    )

    payload = channel.messages[0]
    embed = payload["embed"]
    assert embed.title == "SECURITY BREACH"
    assert embed.fields[0].value == "@Surikacrack"
    assert embed.fields[2].value == "personnel/The_Director.txt"
    assert embed.fields[3].value == "BLOCKED"
