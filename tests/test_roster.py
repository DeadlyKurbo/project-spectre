import types
from roster import build_roster, roster_embed, ROSTER_ROLES


class DummyMember:
    def __init__(self, name):
        self.display_name = name


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
    assert roster[0][2] == ["amy", "Mike", "Zed"]


def test_roster_embed_contains_role_names():
    role_id = ROSTER_ROLES[1][0]
    guild = DummyGuild([DummyRole(role_id, [])])

    embed = roster_embed(guild)
    # The embed should have a field with the role's display name
    assert any(ROSTER_ROLES[1][2] in f.name for f in embed.fields)
