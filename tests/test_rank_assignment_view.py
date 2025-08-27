import importlib
import asyncio

import nextcord


def test_rank_assignment_view(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    importlib.reload(importlib.import_module("constants"))
    op_login = importlib.reload(importlib.import_module("operator_login"))

    op_login.get_or_create_operator(1)

    class DummyRole:
        def __init__(self, rid):
            self.id = rid

    class DummyMember:
        def __init__(self, mid, name="User"):
            self.id = mid
            self.display_name = name
            self.roles = []

        async def add_roles(self, *roles):
            self.roles.extend(roles)

        async def remove_roles(self, *roles):
            for r in roles:
                if r in self.roles:
                    self.roles.remove(r)

    class DummyGuild:
        def __init__(self, members, roles):
            self._members = {m.id: m for m in members}
            self._roles = {r.id: r for r in roles}

        def get_member(self, uid):
            return self._members.get(uid)

        def get_role(self, rid):
            return self._roles.get(rid)

    from roster import ROSTER_ROLES

    roles = [DummyRole(rid) for rid, _, _ in ROSTER_ROLES]
    members = [DummyMember(1, "Alpha")]
    guild = DummyGuild(members, roles)

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        async def create_view():
            return importlib.import_module("archivist").RankAssignmentView(guild)

        view = loop.run_until_complete(create_view())
    finally:
        asyncio.set_event_loop(asyncio.new_event_loop())
        loop.close()
    selects = [c for c in view.children if isinstance(c, nextcord.ui.Select)]
    assert len(selects) == 2
    assign_btn = next(c for c in view.children if isinstance(c, nextcord.ui.Button))
    assert assign_btn.disabled

