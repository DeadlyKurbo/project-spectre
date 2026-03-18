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


class EmbedRetryChannel(DummyChannel):
    def __init__(self):
        super().__init__()
        self.embed_send_attempts = 0

    async def send(self, message=None, *, embed=None, embeds=None):
        if embed is not None:
            self.embed_send_attempts += 1
            raise RuntimeError("embed kwarg rejected")
        selected_embed = None
        if embeds:
            selected_embed = embeds[0]
        self.messages.append({"message": message, "embed": selected_embed})


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

    asyncio.run(context.log_action("Test admin message", guild_id=42))

    assert len(channel.messages) == 1
    payload = channel.messages[0]
    assert payload["message"] is None
    assert payload["embed"].title == "INTELLIGENCE ACCESS"
    assert payload["embed"].fields[2].value == "Test admin message"


def test_log_action_skips_channel_when_guild_id_missing(monkeypatch):
    """When guild_id is None, logs must not be sent to any channel (prevents cross-server leakage)."""
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

    asyncio.run(context.log_action("Test without guild_id"))

    assert channel.messages == []


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
        context.log_action(
            "Unauthorized attempt by @Surikacrack to access personnel/The_Director.txt",
            guild_id=42,
        )
    )

    payload = channel.messages[0]
    embed = payload["embed"]
    assert embed.title == "SECURITY BREACH"
    assert embed.fields[0].value == "@Surikacrack"
    assert embed.fields[2].value == "personnel/The_Director.txt"
    assert embed.fields[4].value == "BLOCKED"


def test_log_action_renders_clearance_request_embed(monkeypatch):
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
        context.log_action(
            "@Surikacrack requested clearance for `personnel/The_Director.txt`.",
            guild_id=42,
        )
    )

    embed = channel.messages[0]["embed"]
    assert embed.title == "CLEARANCE REQUEST"
    assert embed.fields[0].name == "Requester"
    assert embed.fields[2].value == "personnel/The_Director.txt"
    assert embed.fields[3].value == "Pending authorization"


def test_log_action_renders_authorized_action_embed(monkeypatch):
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
        context.log_action(
            "@TheDirector granted @Surikacrack access to `intelligence/Sea_of_Thieves_universe.txt`.",
            guild_id=42,
        )
    )

    embed = channel.messages[0]["embed"]
    assert embed.title == "ACCESS GRANTED"
    assert embed.fields[0].value == "@TheDirector"
    assert embed.fields[2].value == "intelligence/Sea_of_Thieves_universe.txt"
    assert embed.fields[3].value == "Successful retrieval"


def test_log_action_retries_with_embeds_payload(monkeypatch):
    bot = DummyBot()
    channel = EmbedRetryChannel()
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

    asyncio.run(context.log_action("@TheDirector accessed `intelligence/Sea_of_Thieves_universe.txt`."))

    assert channel.embed_send_attempts == 1
    assert len(channel.messages) == 1
    assert channel.messages[0]["embed"].title == "INTELLIGENCE ACCESS"


def test_log_action_truncates_oversized_embed_fields(monkeypatch):
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

    very_long_target = "a" * 1500
    asyncio.run(
        context.log_action(
            f"@TheDirector accessed `{very_long_target}`.",
            guild_id=42,
        )
    )

    embed = channel.messages[0]["embed"]
    file_field = next(field for field in embed.fields if field.name == "Target")
    assert len(file_field.value) == 1024
    assert file_field.value.endswith("...")


def test_log_action_uses_passed_clearance(monkeypatch):
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
        context.log_action(
            "@TheDirector accessed `intel/report.txt`.",
            clearance=5,
            guild_id=42,
        )
    )

    embed = channel.messages[0]["embed"]
    clearance_field = next(field for field in embed.fields if field.name == "Clearance")
    assert clearance_field.value == "Level 5"


def test_log_action_trainee_submission_uses_generic_embed(monkeypatch):
    """Trainee submission approve/deny/request-changes must not show SECURITY BREACH."""
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
        context.log_action(
            "@TheDirector denied trainee submission 42: needs more detail.",
            guild_id=42,
        )
    )

    embed = channel.messages[0]["embed"]
    assert embed.title == "INTELLIGENCE ACCESS"
    assert embed.title != "SECURITY BREACH"


def test_log_action_skips_when_event_disabled(monkeypatch):
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

    monkeypatch.setattr(
        "spectre.context.get_server_config",
        lambda gid: {"ADMIN_LOG_CHANNEL_ID": 555, "ADMIN_AUDIT_EVENTS": {"file_access": False}},
    )
    monkeypatch.setattr("spectre.context.get_dashboard_logging_channels", lambda _gid: {})

    asyncio.run(
        context.log_action(
            "@TheDirector accessed `intel/report.txt`.",
            event_type="file_access",
            guild_id=42,
        )
    )

    assert len(channel.messages) == 0
