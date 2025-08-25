import asyncio
import importlib
import types


class DummyRole:
    def __init__(self, position):
        self.position = position


class DummyGuild:
    def __init__(self, role, expected_id):
        self._role = role
        self.expected_id = expected_id
        self.roles = []

    def get_role(self, rid):
        assert rid == self.expected_id
        return self._role


class DummyResponse:
    def __init__(self):
        self.content = None

    async def send_message(self, *args, **kwargs):
        if args:
            self.content = args[0]
        else:
            self.content = kwargs.get("content")


class DummyInteraction:
    def __init__(self, guild):
        self.guild = guild
        self.user = types.SimpleNamespace(top_role=DummyRole(position=10))
        self.response = DummyResponse()


def test_protocol_epsilon_uses_role_id(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    main = importlib.reload(importlib.import_module("main"))

    role = DummyRole(position=5)
    guild = DummyGuild(role, main.CLASSIFIED_ROLE_ID)
    interaction = DummyInteraction(guild)

    async def run():
        await main.protocol_epsilon(interaction)
        assert interaction.response.content.startswith("[ACCESS NODE: EPSILON]")

    asyncio.run(run())
