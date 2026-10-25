import importlib, asyncio
from types import SimpleNamespace

import utils


def test_access_sequence_throttle(monkeypatch, tmp_path):
    monkeypatch.setenv('DISCORD_TOKEN', 'x')
    monkeypatch.setenv('GUILD_ID', '1')
    monkeypatch.setenv('MENU_CHANNEL_ID', '1')

    ddir = tmp_path / 'intel'
    ddir.mkdir()
    (ddir / 'file1.txt').write_text('dummy')

    utils.DOSSIERS_DIR = str(tmp_path)
    main = importlib.reload(importlib.import_module('main'))
    main.DOSSIERS_DIR = str(tmp_path)
    import views
    monkeypatch.setattr(views, 'check_temp_clearance', lambda *a, **k: False)
    monkeypatch.setattr(main, 'get_required_roles', lambda c, i: {1})
    monkeypatch.setattr(main, 'log_action', lambda *a, **k: None)
    monkeypatch.setattr(views, '_last_verified', {})

    calls = []
    async def fake_run_access_sequence(*a, **k):
        calls.append(1)
    monkeypatch.setattr(views, 'run_access_sequence', fake_run_access_sequence)

    now = 1000
    monkeypatch.setattr(views.time, 'time', lambda: now)

    select = main.CategorySelect()
    select.category = 'intel'
    async def dummy_show_item(self, interaction, item_rel_base, use_followup=False):
        return None
    monkeypatch.setattr(main.CategorySelect, '_show_item', dummy_show_item)

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
        async def send_message(self, *a, **k):
            pass
    interaction = SimpleNamespace(user=User(), guild=Guild(), response=Response(), followup=SimpleNamespace(send=lambda *a, **k: None))

    asyncio.run(select._show_with_sequence(interaction, 'file1'))
    asyncio.set_event_loop(asyncio.new_event_loop())
    assert len(calls) == 1

    asyncio.run(select._show_with_sequence(interaction, 'file1'))
    asyncio.set_event_loop(asyncio.new_event_loop())
    assert len(calls) == 1

    now += 601
    monkeypatch.setattr(views.time, 'time', lambda: now)
    asyncio.run(select._show_with_sequence(interaction, 'file1'))
    asyncio.set_event_loop(asyncio.new_event_loop())
    assert len(calls) == 2
