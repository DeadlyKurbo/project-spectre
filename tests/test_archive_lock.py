import importlib, asyncio
from types import SimpleNamespace

def test_archive_lock(monkeypatch):
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
        id = 1
        owner_id = 2

    class User:
        id = 1
        mention = '<@1>'
        roles = [Role(main.ARCHIVIST_ROLE_ID)]
        guild_permissions = Perms()

    guild = Guild()
    user = User()
    user.guild = guild

    class Response:
        def __init__(self):
            self.kwargs = None

        async def send_message(self, *args, embed=None, view=None, ephemeral=False, content=None):
            if args:
                content = args[0]
            self.kwargs = {
                'embed': embed,
                'view': view,
                'ephemeral': ephemeral,
                'content': content,
            }

    inter = SimpleNamespace(user=user, guild=guild, response=Response())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main.archivist_cmd(inter))
    assert isinstance(inter.response.kwargs['view'], arch.ArchivistLimitedConsoleView)

    arch.lock_archive(guild.id)
    inter.response.kwargs = None
    loop.run_until_complete(main.archivist_cmd(inter))
    assert inter.response.kwargs['content'] == ' Archive access locked.'

    arch.unlock_archive(guild.id)
    inter.response.kwargs = None
    loop.run_until_complete(main.archivist_cmd(inter))
    assert isinstance(inter.response.kwargs['view'], arch.ArchivistLimitedConsoleView)
    loop.close()
    asyncio.set_event_loop(asyncio.new_event_loop())


def test_high_command_lock_button(monkeypatch):
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
        id = 1
        owner_id = 2

    class User:
        id = 1
        mention = '<@1>'
        roles = [Role(main.HIGH_COMMAND_ROLE_ID)]
        guild_permissions = Perms()

    guild = Guild()
    user = User()
    user.guild = guild

    class Response:
        def __init__(self):
            self.kwargs = None
            self.last_view = None

        def is_done(self):
            return False

        async def send_message(self, *args, embed=None, view=None, ephemeral=False, content=None):
            if args:
                content = args[0]
            self.kwargs = {
                'embed': embed,
                'view': view,
                'ephemeral': ephemeral,
                'content': content,
            }

        async def edit_message(self, *, view=None):
            self.last_view = view

    class Followup:
        def __init__(self):
            self.sent = None

        async def send(self, content, ephemeral=False):
            self.sent = {'content': content, 'ephemeral': ephemeral}

    inter = SimpleNamespace(user=user, guild=guild, response=Response())

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main.archivist_cmd(inter))

    view = inter.response.kwargs['view']
    assert isinstance(view, arch.ArchivistConsoleView)
    assert view._lock_button is not None
    assert view._lock_button.label == ' Engage Lockdown'
    arch.unlock_archive(guild.id)

    sent_logs = []

    async def fake_log(message: str, *, broadcast: bool = True, **kwargs):
        sent_logs.append(message)

    monkeypatch.setattr(main, 'log_action', fake_log)

    followup = Followup()
    inter_press = SimpleNamespace(user=user, guild=guild, response=inter.response, followup=followup, edit_original_message=lambda **kwargs: None)

    loop.run_until_complete(view.toggle_archive_lockdown(inter_press))
    assert arch.is_archive_locked(guild.id)
    assert view._lock_button.label == ' Release Lockdown'
    assert followup.sent == {'content': ' Archive lockdown engaged.', 'ephemeral': True}
    assert sent_logs[-1].endswith('engaged the archive lockdown.')

    followup2 = Followup()
    inter_press2 = SimpleNamespace(user=user, guild=guild, response=inter.response, followup=followup2, edit_original_message=lambda **kwargs: None)
    loop.run_until_complete(view.toggle_archive_lockdown(inter_press2))
    assert not arch.is_archive_locked(guild.id)
    assert view._lock_button.label == ' Engage Lockdown'
    assert followup2.sent == {'content': ' Archive lockdown lifted.', 'ephemeral': True}
    assert sent_logs[-1].endswith('lifted the archive lockdown.')

    loop.close()
    asyncio.set_event_loop(asyncio.new_event_loop())
