import importlib, asyncio


def test_lead_archivist_category_button(monkeypatch):
    monkeypatch.setenv('DISCORD_TOKEN', 'x')
    monkeypatch.setenv('GUILD_ID', '1')
    monkeypatch.setenv('MENU_CHANNEL_ID', '1')
    arch = importlib.reload(importlib.import_module('archivist'))

    class Perms:
        administrator = False

    class Role:
        def __init__(self, rid):
            self.id = rid

    class Guild:
        owner_id = 2

    class User:
        id = 1
        mention = '<@1>'
        roles = [Role(arch.ARCHIVIST_ROLE_ID)]
        guild_permissions = Perms()
        guild = Guild()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run():
        return arch.FileManagementView(arch.ArchivistConsoleView(User()))

    view = loop.run_until_complete(run())
    labels = [item.label for item in view.children]
    loop.close()
    asyncio.set_event_loop(asyncio.new_event_loop())
    assert ' Edit Categories' in labels
