import importlib, asyncio
from types import SimpleNamespace

import utils


def test_plain_text_links_clickable(monkeypatch, tmp_path):
    monkeypatch.setenv('DISCORD_TOKEN', 'x')
    monkeypatch.setenv('GUILD_ID', '1')
    monkeypatch.setenv('MENU_CHANNEL_ID', '1')

    ddir = tmp_path / 'intel'
    ddir.mkdir()
    (ddir / 'file1.txt').write_text('check http://example.com')

    utils.DOSSIERS_DIR = str(tmp_path)
    main = importlib.reload(importlib.import_module('main'))
    main.DOSSIERS_DIR = str(tmp_path)

    import views
    monkeypatch.setattr(views, 'random', SimpleNamespace(random=lambda: 1.0))
    monkeypatch.setattr(views, 'check_temp_clearance', lambda *a, **k: False)
    monkeypatch.setattr(main, 'get_required_roles', lambda c, i: {1})
    async def _no_log(msg):
        return None
    monkeypatch.setattr(main, 'log_action', _no_log)

    select = main.CategorySelect()
    select.category = 'intel'

    class Perms:
        administrator = False
    class Role:
        def __init__(self, rid):
            self.id = rid
    class User:
        id = 42
        roles = [Role(1)]
        guild_permissions = Perms()
        def __str__(self):
            return 'member1'
    class Guild:
        owner_id = 99
    class Response:
        def __init__(self):
            self.kwargs = None
        async def edit_message(self, *args, **kwargs):
            self.kwargs = kwargs
        async def send_message(self, *args, **kwargs):
            self.kwargs = kwargs
    class Followup:
        async def send(self, *args, **kwargs):
            pass

    interaction = SimpleNamespace(
        user=User(),
        guild=Guild(),
        response=Response(),
        followup=Followup(),
    )

    asyncio.run(select._show_item(interaction, 'file1'))
    asyncio.set_event_loop(asyncio.new_event_loop())

    embed = interaction.response.kwargs['embed']
    assert '```' not in embed.fields[1].value
    assert 'http://example.com' in embed.fields[1].value
