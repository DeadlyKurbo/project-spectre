import asyncio
from roster import build_roster, roster_embed, ROSTER_ROLES, RosterMenuView


class DummyMember:
    def __init__(self, name):
        self.display_name = name
        self.mention = f"<@{name}>"


class DummyRole:
    def __init__(self, role_id, members):
        self.id = role_id
        self.members = members


class DummyGuild:
    def __init__(self, roles):
        self._roles = {r.id: r for r in roles}

    def get_role(self, role_id):
        return self._roles.get(role_id)


def test_build_roster_orders_members():
    members = [DummyMember("Zed"), DummyMember("amy"), DummyMember("Mike")]
    role_id = ROSTER_ROLES[0][0]
    guild = DummyGuild([DummyRole(role_id, members)])

    roster = build_roster(guild)
    assert roster[0][2] == ["<@amy>", "<@Mike>", "<@Zed>"]


def test_roster_embed_contains_role_names():
    role_id = ROSTER_ROLES[1][0]
    guild = DummyGuild([DummyRole(role_id, [])])

    embed = roster_embed(guild)
    # The embed should have a field with the role's display name
    assert any(ROSTER_ROLES[1][2] in f.name for f in embed.fields)


def test_roster_menu_contains_roles():
    guild = DummyGuild([DummyRole(rid, []) for rid, _, _ in ROSTER_ROLES])
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)

        async def _make_view():
            return RosterMenuView(guild)

        view = loop.run_until_complete(_make_view())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        asyncio.set_event_loop(None)
    labels = [opt.label for opt in view.children[0].options]
    assert ROSTER_ROLES[0][2] in labels


def test_roster_embed_chunks_long_lists():
    role_id = ROSTER_ROLES[0][0]
    members = [DummyMember(str(i)) for i in range(25)]
    guild = DummyGuild([DummyRole(role_id, members)])

    embed = roster_embed(guild)
    role_fields = [f for f in embed.fields if ROSTER_ROLES[0][2] in f.name]
    assert len(role_fields) == 2
    assert role_fields[0].value.startswith("1. <@0>")
    assert role_fields[1].value.startswith("21.")
