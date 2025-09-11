import importlib
import asyncio
import importlib
from types import SimpleNamespace


def _reload(monkeypatch):
    monkeypatch.setenv('DISCORD_TOKEN', 'x')
    monkeypatch.setenv('GUILD_ID', '1')
    monkeypatch.setenv('MENU_CHANNEL_ID', '1')
    return importlib.reload(importlib.import_module('archivist'))


def test_link_personnel_files(monkeypatch):
    arch = _reload(monkeypatch)
    monkeypatch.setattr(arch, 'save_json', lambda *a, **k: None)
    arch._PERSONNEL_LINKS.clear()
    arch.link_personnel_file(1, 'intel/secret.txt')
    assert arch._PERSONNEL_LINKS[1] == ['intel/secret.txt']
    monkeypatch.setattr(
        arch,
        '_find_existing_item_key',
        lambda c, r: (f'personnel/{r}.txt', '.txt'),
    )
    assert arch.get_personnel_files(1) == ['personnel/1.txt', 'intel/secret.txt']


def test_file_management_view_link_button(monkeypatch):
    arch = _reload(monkeypatch)

    class Role:
        def __init__(self, rid):
            self.id = rid

    class Perms:
        administrator = False

    user = SimpleNamespace(
        id=1,
        roles=[Role(arch.LEAD_ARCHIVIST_ROLE_ID)],
        guild_permissions=Perms(),
        guild=SimpleNamespace(owner_id=2),
    )
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _create():
        console = arch.ArchivistConsoleView(user)
        return arch.FileManagementView(console)

    view = loop.run_until_complete(_create())
    loop.close()
    asyncio.set_event_loop(asyncio.new_event_loop())
    assert any(item.label == 'Link Personnel' for item in view.children)


