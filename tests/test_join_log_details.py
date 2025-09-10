import asyncio
import types

import main
import moderation


class DummyLoop:
    def create_task(self, coro):
        return asyncio.create_task(coro)


class DummyHttp:
    async def get_user_profile(self, user_id):
        return {"bio": "Bio text"}


class DummyChannel:
    def __init__(self):
        self.messages = []

    async def send(self, *args, **kwargs):
        self.messages.append((args, kwargs))


class DummyGuild:
    def __init__(self):
        self.members = []

    async def bans(self):
        return []


class DummyMember:
    def __init__(self, guild):
        self.guild = guild
        self.id = 99
        self.name = "user"
        self.display_name = "user"
        self.roles = []
        self.bot = False
        self.display_avatar = types.SimpleNamespace(url="http://example.com/pic.png")
        self.created_at = main.START_TIME
        self.mention = "<@99>"

    def __str__(self):
        return self.name


class DummyBot:
    def __init__(self, channel):
        self.loop = DummyLoop()
        self._channel = channel
        self.http = DummyHttp()

    def get_channel(self, _):
        return self._channel


def test_join_log_contains_extra_details(monkeypatch):
    channel = DummyChannel()
    bot = DummyBot(channel)
    cog = moderation.Moderation(bot)
    main.LOG_CHANNEL_ID = 1
    main.MIN_ACCOUNT_AGE_DAYS = 0

    async def fake_log_action(*args, **kwargs):
        pass

    main.log_action = fake_log_action
    monkeypatch.setattr(moderation, "list_member_notes", lambda uid: ["[2024-01-01] note"])

    member = DummyMember(DummyGuild())
    asyncio.run(cog.on_member_join(member))
    assert channel.messages, "Join info should be sent"
    embed = channel.messages[0][1]["embed"]
    fields = {f.name: f.value for f in embed.fields}
    assert fields["About me"] == "Bio text"
    assert "note" in fields["Previous moderation"]
    asyncio.set_event_loop(asyncio.new_event_loop())
