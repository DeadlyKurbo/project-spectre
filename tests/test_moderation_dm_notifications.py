import asyncio
import types

import main
from moderation import Moderation


class DummyPermissions:
    def __init__(self):
        self.kick_members = True
        self.ban_members = True
        self.moderate_members = True


class DummyModerator:
    def __init__(self):
        self.guild_permissions = DummyPermissions()
        self.mention = "<@mod>"


class DummyMember:
    def __init__(self):
        self.sent = []
        self.mention = "<@target>"
        self.id = 1
        self.guild = None
        self.timeout_called = None

    async def send(self, msg):
        self.sent.append(msg)

    async def timeout(self, duration, reason=None):
        self.timeout_called = (duration, reason)


class DummyGuild:
    def __init__(self):
        self.name = "TestGuild"
        self.kicked = []
        self.banned = []
        self.unbanned = []

    async def kick(self, member, reason=None):
        self.kicked.append((member, reason))

    async def ban(self, member, reason=None):
        self.banned.append((member, reason))

    async def unban(self, user, reason=None):
        self.unbanned.append((user, reason))

    async def bans(self):
        return [types.SimpleNamespace(user=m) for m, _ in self.banned]


class DummyLoop:
    def create_task(self, coro):
        return asyncio.create_task(coro)


class DummyBot:
    def __init__(self):
        self.loop = DummyLoop()


class DummyResponse:
    def __init__(self):
        self.messages = []

    async def send_message(self, message, ephemeral=False):
        self.messages.append((message, ephemeral))


class DummyInteraction:
    def __init__(self, guild):
        self.guild = guild
        self.user = DummyModerator()
        self.response = DummyResponse()
        self.channel = None


async def run_kick():
    guild = DummyGuild()
    member = DummyMember()
    interaction = DummyInteraction(guild)
    cog = Moderation(DummyBot())

    logs = []

    async def fake_log_action(message: str, *, broadcast: bool = True):
        logs.append(message)

    main.log_action = fake_log_action

    await cog.kick_member(interaction, member, reason="spamming")
    return member, logs


async def run_ban():
    guild = DummyGuild()
    member = DummyMember()
    interaction = DummyInteraction(guild)
    cog = Moderation(DummyBot())

    logs = []

    async def fake_log_action(message: str, *, broadcast: bool = True):
        logs.append(message)

    main.log_action = fake_log_action

    await cog.ban_member(interaction, member, reason="toxicity", duration=10, unit="minutes")
    return member, logs, guild


async def run_ban_days():
    guild = DummyGuild()
    member = DummyMember()
    interaction = DummyInteraction(guild)
    cog = Moderation(DummyBot())

    captured = {}

    async def fake_schedule(self, g, uid, delay):
        captured["delay"] = delay

    cog._schedule_unban = fake_schedule.__get__(cog, Moderation)

    await cog.ban_member(interaction, member, reason="toxicity", duration=2, unit="days")
    await asyncio.sleep(0)
    return captured.get("delay")


async def run_mute():
    guild = DummyGuild()
    member = DummyMember()
    interaction = DummyInteraction(guild)
    cog = Moderation(DummyBot())

    logs = []

    async def fake_log_action(message: str, *, broadcast: bool = True):
        logs.append(message)

    main.log_action = fake_log_action

    await cog.mute_member(interaction, member, minutes=5, reason="spam")
    return member, logs


async def run_unban():
    guild = DummyGuild()
    user = types.SimpleNamespace(id=2, mention="<@2>")
    guild.banned.append((user, "old"))
    interaction = DummyInteraction(guild)
    cog = Moderation(DummyBot())

    logs = []

    async def fake_log_action(message: str, *, broadcast: bool = True):
        logs.append(message)

    main.log_action = fake_log_action

    await cog.unban_member(interaction, user_id=2, reason="appeal")
    return guild, logs


def test_kick_sends_dm_and_logs():
    member, logs = asyncio.run(run_kick())
    assert member.sent and "spamming" in member.sent[0]
    assert logs and "kicked" in logs[0]


def test_ban_sends_dm_and_logs():
    member, logs, guild = asyncio.run(run_ban())
    assert member.sent and "toxicity" in member.sent[0]
    assert guild.banned, "Guild.ban should be called"
    assert logs and "banned" in logs[0]


def test_ban_duration_units_days():
    delay = asyncio.run(run_ban_days())
    assert delay == 2 * 24 * 60 * 60


def test_mute_sends_dm_and_logs():
    member, logs = asyncio.run(run_mute())
    assert member.sent and "spam" in member.sent[0]
    assert member.timeout_called is not None
    assert logs and "muted" in logs[0]


def test_unban_works_and_logs():
    guild, logs = asyncio.run(run_unban())
    assert guild.unbanned, "Guild.unban should be called"
    assert logs and "unbanned" in logs[0]
