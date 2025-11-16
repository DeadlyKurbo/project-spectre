import asyncio
import types

import nextcord

from cogs.archive import ArchiveCog

from spectre.commands.archive_menu import spawn_archive_menu_command


class DummyPermissions:
    def __init__(self, view=True, send=True, embed=True):
        self.view_channel = view
        self.send_messages = send
        self.embed_links = embed


class DummyChannel:
    def __init__(self, channel_id: int):
        self.id = channel_id
        self.mention = f"<#{channel_id}>"
        self.type = nextcord.ChannelType.text

    def permissions_for(self, _member):
        return DummyPermissions()


class DummyGuild:
    def __init__(self, channel: DummyChannel):
        self.id = 1
        self._channel = channel
        self.me = types.SimpleNamespace(id=999)

    def get_channel(self, cid: int):
        return self._channel if cid == self._channel.id else None

    get_channel_or_thread = get_channel

    def get_member(self, member_id: int):
        if member_id == self.me.id:
            return self.me
        return None


class DummyResponse:
    def __init__(self):
        self._messages: list[str] = []
        self._deferred = False

    async def send_message(self, content: str, *, ephemeral: bool = False):
        _ = ephemeral
        self._messages.append(content)
        self._deferred = True

    async def defer(self, *, ephemeral: bool = False):
        _ = ephemeral
        self._deferred = True

    def is_done(self) -> bool:
        return self._deferred


class DummyFollowup:
    def __init__(self):
        self.messages: list[tuple[str, bool]] = []

    async def send(self, content: str, *, ephemeral: bool = False):
        self.messages.append((content, ephemeral))


class DummyInteraction:
    def __init__(self, guild: DummyGuild, cog):
        self.guild = guild
        self.client = types.SimpleNamespace(get_cog=lambda name: cog)
        self.response = DummyResponse()
        self.followup = DummyFollowup()
        self.user = types.SimpleNamespace(roles=[])


def _dummy_context():
    bot = types.SimpleNamespace(user=types.SimpleNamespace(id=999))
    return types.SimpleNamespace(bot=bot)


def test_spawn_refreshes_modern_menu_when_legacy_missing(monkeypatch):
    channel = DummyChannel(42)
    guild = DummyGuild(channel)
    interaction = DummyInteraction(guild, cog=None)
    context = _dummy_context()

    refreshed = {}

    async def fake_refresh(target_guild):
        refreshed["guild"] = target_guild

    monkeypatch.setattr(
        "spectre.commands.archive_menu.refresh_menus",
        fake_refresh,
    )
    monkeypatch.setattr(
        "spectre.commands.archive_menu.get_server_config",
        lambda gid: {"MENU_CHANNEL_ID": channel.id},
    )

    asyncio.run(spawn_archive_menu_command(context, interaction))

    assert refreshed.get("guild") is guild
    assert interaction.followup.messages
    message, ephemeral = interaction.followup.messages[-1]
    assert "Archive console refreshed" in message
    assert ephemeral is True


class DummyArchiveCog(ArchiveCog):
    def __init__(self, channel: DummyChannel):
        self._channel = channel

    def _resolve_menu_channel(self, guild):
        return self._channel, None

    async def deploy_for_guild(self, guild):
        return "posted message 5"


def test_spawn_falls_back_to_legacy_when_modern_channel_missing(monkeypatch):
    channel = DummyChannel(99)
    guild = DummyGuild(channel)
    cog = DummyArchiveCog(channel)
    interaction = DummyInteraction(guild, cog=cog)
    context = _dummy_context()

    async def fake_refresh(_guild):
        raise AssertionError("refresh_menus should not be called without config")

    monkeypatch.setattr(
        "spectre.commands.archive_menu.refresh_menus",
        fake_refresh,
    )
    monkeypatch.setattr(
        "spectre.commands.archive_menu.get_server_config",
        lambda gid: {},
    )

    asyncio.run(spawn_archive_menu_command(context, interaction))

    assert interaction.followup.messages
    message, ephemeral = interaction.followup.messages[-1]
    assert "Archive menu posted" in message
    assert ephemeral is True
