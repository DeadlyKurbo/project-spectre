import asyncio
import asyncio
from datetime import datetime, UTC, timedelta
import types

import main
from moderation import Moderation


class DummyGuild:
    def __init__(self):
        self.banned = []
        self.members = []

    async def ban(self, member, reason=None):
        self.banned.append((member, reason))

    async def bans(self):
        return []

    async def unban(self, user, reason=None):
        pass


class DummyChannel:
    def __init__(self):
        self.messages = []

    async def send(self, *args, **kwargs):
        self.messages.append((args, kwargs))


class DummyMember:
    def __init__(self, guild):
        self.guild = guild
        self.id = 42
        self.name = "foo"
        self.display_name = "foo"
        self.roles = []
        self.bot = False
        self.display_avatar = types.SimpleNamespace(url="http://example.com/a.png")
        self.created_at = datetime.now(UTC) - timedelta(days=1)
        self.mention = "<@42>"

    def __str__(self):
        return self.name


class DummyLoop:
    def create_task(self, coro):
        return asyncio.create_task(coro)


class DummyBot:
    def __init__(self, channel):
        self.loop = DummyLoop()
        self._channel = channel

    def get_channel(self, _):
        return self._channel

    async def fetch_user(self, user_id):
        return types.SimpleNamespace(mention=f"<@{user_id}>")


async def run_test():
    channel = DummyChannel()
    bot = DummyBot(channel)
    cog = Moderation(bot)
    main.JOIN_LOG_CHANNEL_ID = 123
    main.LOG_CHANNEL_ID = 456
    main.MIN_ACCOUNT_AGE_DAYS = 14

    async def fake_log_action(*args, **kwargs):
        pass

    main.log_action = fake_log_action

    guild = DummyGuild()
    member = DummyMember(guild)

    calls = {}

    async def fake_schedule(self, g, uid, delay):
        calls["data"] = (g, uid, delay)

    cog._schedule_unban = fake_schedule.__get__(cog, Moderation)

    await cog.on_member_join(member)
    await asyncio.sleep(0)
    return guild, channel, calls


def test_account_age_ban():
    guild, channel, calls = asyncio.run(run_test())
    assert guild.banned, "Member should be banned for young account"
    assert channel.messages, "Join info should be logged"
    assert calls["data"][1] == 42
    assert calls["data"][2] > 0
    asyncio.set_event_loop(asyncio.new_event_loop())
