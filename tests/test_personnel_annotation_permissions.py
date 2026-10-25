import importlib
from types import SimpleNamespace
import asyncio


def _make_user(role_id):
    class Perms:
        administrator = False

    class Role:
        def __init__(self, rid):
            self.id = rid

    class Guild:
        owner_id = 0

    user = SimpleNamespace(
        id=42,
        roles=[Role(role_id)],
        guild=Guild(),
        guild_permissions=Perms(),
    )
    return user


def test_personnel_annotation_permissions(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")

    arch = importlib.reload(importlib.import_module("archivist"))

    monkeypatch.setattr(arch, "list_categories", lambda: ["personnel", "intel"])

    regular = _make_user(arch.ARCHIVIST_ROLE_ID)
    lead = _make_user(arch.LEAD_ARCHIVIST_ROLE_ID)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def create_views():
        return arch.AnnotateFileView(regular), arch.AnnotateFileView(lead)

    reg_view, lead_view = loop.run_until_complete(create_views())
    loop.close()
    asyncio.set_event_loop(asyncio.new_event_loop())

    categories = [opt.value for opt in reg_view.children[0].options]
    categories_lead = [opt.value for opt in lead_view.children[0].options]

    assert "personnel" not in categories
    assert "personnel" in categories_lead
