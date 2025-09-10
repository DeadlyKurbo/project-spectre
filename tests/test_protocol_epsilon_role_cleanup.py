import asyncio
import importlib


class DummyRole:
    def __init__(self, rid, position=0):
        self.id = rid
        self.position = position
        self.members = []


class DummyMember:
    def __init__(self, roles):
        self.roles = list(roles)

    async def remove_roles(self, *roles, reason=None):
        for role in roles:
            if role in self.roles:
                self.roles.remove(role)


class DummyGuild:
    def __init__(self, roles, members):
        self.roles = roles
        self.channels = []
        self.members = members


def test_apply_protocol_epsilon_removes_rank_roles(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    main = importlib.reload(importlib.import_module("main"))

    monkeypatch.setattr(
        main,
        "ROSTER_ROLES",
        [
            (1, "", "Owner"),
            (2, "", "Fleet Admiral"),
            (3, "", "Captain"),
        ],
        raising=False,
    )

    owner_role = DummyRole(1, 100)
    fleet_role = DummyRole(2, 90)
    captain_role = DummyRole(3, 80)

    member_owner = DummyMember([owner_role, captain_role])
    member_fleet = DummyMember([fleet_role])
    member_other = DummyMember([captain_role])

    guild = DummyGuild(
        roles=[owner_role, fleet_role, captain_role],
        members=[member_owner, member_fleet, member_other],
    )

    classified_role = DummyRole(999, 1000)

    async def run():
        await main.apply_protocol_epsilon(guild, classified_role)

    asyncio.run(run())
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert member_owner.roles == [owner_role]
    assert member_fleet.roles == [fleet_role]
    assert member_other.roles == []

