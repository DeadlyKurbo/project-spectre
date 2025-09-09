import importlib
import asyncio
import types
import nextcord


def test_role_creation_logged(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")
    main = importlib.reload(importlib.import_module("main"))
    from moderation import Moderation

    logs = []

    async def fake_log(message: str, *, broadcast: bool = True):
        logs.append(message)

    monkeypatch.setattr(main, "log_action", fake_log)

    class DummyUser:
        mention = "<@5>"

    class DummyEntry:
        def __init__(self, user, target):
            self.user = user
            self.target = target

    class DummyAuditLogs:
        def __init__(self, entries):
            self.entries = entries

        def __aiter__(self):
            async def gen():
                for e in self.entries:
                    yield e
            return gen()

    class DummyGuild:
        def __init__(self, entries):
            self._entries = entries

        def audit_logs(self, **kwargs):
            return DummyAuditLogs(self._entries)

    role = types.SimpleNamespace(
        id=10,
        mention="@newrole",
        permissions=nextcord.Permissions(administrator=True),
        guild=DummyGuild([DummyEntry(DummyUser(), types.SimpleNamespace(id=10))]),
    )

    mod = Moderation(main.bot)
    asyncio.run(mod.on_guild_role_create(role))
    asyncio.set_event_loop(asyncio.new_event_loop())
    assert logs == [" <@5> created role @newrole with permissions: administrator."]
