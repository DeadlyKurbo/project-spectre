import importlib, asyncio
from types import SimpleNamespace

import utils


def test_show_item_paginates_long_content(monkeypatch, tmp_path):
    monkeypatch.setenv('DISCORD_TOKEN', 'x')
    monkeypatch.setenv('GUILD_ID', '1')
    monkeypatch.setenv('MENU_CHANNEL_ID', '1')

    ddir = tmp_path / 'intel'
    ddir.mkdir()
    long_text = 'a' * 1000 + 'b' * 1000
    (ddir / 'file1.txt').write_text(long_text)

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
        mention = '<@42>'
    class Guild:
        owner_id = 99
    class Response:
        def __init__(self):
            self.kwargs = None
        async def edit_message(self, *a, **k):
            self.kwargs = k
        async def send_message(self, *a, **k):
            self.kwargs = k
    class Followup:
        async def send(self, *a, **k):
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
    view = interaction.response.kwargs['view']
    first_page = embed.fields[1].value
    assert len(first_page) <= 1024
    assert '…(truncated)' not in first_page
    assert embed.fields[1].name == 'Contents (page 1/2)'
    assert 'a' * 1000 in first_page

    next_btn = next(item for item in view.children if getattr(item, 'custom_id', '') == 'next_page_v1')
    prev_btn = next(item for item in view.children if getattr(item, 'custom_id', '') == 'prev_page_v1')
    assert not next_btn.disabled
    assert prev_btn.disabled

    inter2 = SimpleNamespace(response=Response())
    asyncio.run(next_btn.callback(inter2))
    asyncio.set_event_loop(asyncio.new_event_loop())

    embed2 = inter2.response.kwargs['embed']
    page2 = embed2.fields[1].value
    assert '…(truncated)' not in page2
    assert 'b' * 1000 in page2
    assert page2 != first_page
    assert embed2.fields[1].name == 'Contents (page 2/2)'
    assert next_btn.disabled
    assert not prev_btn.disabled

    inter3 = SimpleNamespace(response=Response())
    asyncio.run(prev_btn.callback(inter3))
    asyncio.set_event_loop(asyncio.new_event_loop())

    embed3 = inter3.response.kwargs['embed']
    assert embed3.fields[1].value == first_page
