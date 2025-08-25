import importlib, asyncio
from types import SimpleNamespace

def test_archivist_trainee_menu(monkeypatch):
    monkeypatch.setenv('DISCORD_TOKEN', 'x')
    monkeypatch.setenv('GUILD_ID', '1')
    monkeypatch.setenv('MENU_CHANNEL_ID', '1')

    arch = importlib.reload(importlib.import_module('archivist'))
    main = importlib.reload(importlib.import_module('main'))

    async def no_hiccup(_):
        return False
    monkeypatch.setattr(main, 'maybe_simulate_hiccup', no_hiccup)

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
        roles = [Role(main.TRAINEE_ROLE_ID)]
        guild_permissions = Perms()

    guild = Guild()
    user = User()
    user.guild = guild

    class Response:
        def __init__(self):
            self.kwargs = None
        async def send_message(self, *, embed=None, view=None, ephemeral=False):
            self.kwargs = {'embed': embed, 'view': view, 'ephemeral': ephemeral}

    inter = SimpleNamespace(user=user, guild=guild, response=Response())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main.archivist_cmd(inter))
    loop.close()
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert isinstance(inter.response.kwargs['view'], arch.ArchivistTraineeConsoleView)
    assert inter.response.kwargs['embed'].title == main.TRAINEE_ARCHIVIST_TITLE
