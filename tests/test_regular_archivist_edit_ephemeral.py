import importlib, asyncio
from types import SimpleNamespace


def test_regular_archivist_edit_ephemeral(monkeypatch):
    monkeypatch.setenv('DISCORD_TOKEN', 'x')
    monkeypatch.setenv('GUILD_ID', '1')
    monkeypatch.setenv('MENU_CHANNEL_ID', '1')

    arch = importlib.reload(importlib.import_module('archivist'))

    async def dummy_sleep(*args, **kwargs):
        pass
    monkeypatch.setattr(arch.asyncio, 'sleep', dummy_sleep)
    monkeypatch.setattr(arch.random, 'randint', lambda a, b: a)

    class DummyMessage:
        async def edit(self, **kwargs):
            self.kwargs = kwargs

    class DummyResponse:
        async def defer(self, *, ephemeral=False):
            self.deferred = ephemeral

    class DummyFollowup:
        def __init__(self):
            self.kwargs = None
        async def send(self, *, embed=None, ephemeral=False, **kwargs):
            self.kwargs = {'embed': embed, 'ephemeral': ephemeral}
            return DummyMessage()

    class Perms:
        administrator = False

    class Role:
        def __init__(self, rid):
            self.id = rid

    class User:
        id = 1
        mention = '<@1>'
        roles = [Role(arch.ARCHIVIST_ROLE_ID)]
        guild_permissions = Perms()

    class Guild:
        owner_id = 2

    inter = SimpleNamespace(user=User(), guild=Guild(), response=DummyResponse(), followup=DummyFollowup())

    class DummyEditFileView:
        def __init__(self, *args, **kwargs):
            pass
    monkeypatch.setattr(arch, 'EditFileView', DummyEditFileView)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run_test():
        view = arch.ArchivistLimitedConsoleView(inter.user)
        await view.open_edit(inter)

    loop.run_until_complete(run_test())
    loop.close()
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert inter.followup.kwargs['ephemeral'] is True
