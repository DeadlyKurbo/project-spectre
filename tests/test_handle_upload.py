import importlib, asyncio, types, threading, time, os

import utils, archivist

class DummyAttachment:
    def __init__(self, filename, content):
        self.filename = filename
        self._content = content
    async def read(self):
        return self._content.encode('utf-8')

class DummyChannel:
    def __init__(self, cid):
        self.id = cid
        self.messages = []
    async def send(self, msg):
        self.messages.append(msg)

class DummyAuthor:
    bot = False
    mention = '<@1>'
    def __str__(self):
        return 'tester'


def test_handle_upload_saves_file(tmp_path, monkeypatch):
    monkeypatch.setenv('DISCORD_TOKEN', 'x')
    monkeypatch.setenv('GUILD_ID', '1')
    monkeypatch.setenv('MENU_CHANNEL_ID', '1')
    main = importlib.reload(importlib.import_module('main'))
    # Redirect dossier directory to temporary path
    monkeypatch.setattr(utils, 'DOSSIERS_DIR', tmp_path)
    monkeypatch.setattr(main, 'DOSSIERS_DIR', tmp_path)
    (tmp_path / 'intel').mkdir()

    channel = DummyChannel(main.UPLOAD_CHANNEL_ID)
    attachment = DummyAttachment('report.json', '{"a":1}')
    author = DummyAuthor()
    author.roles = [types.SimpleNamespace(id=main.ARCHIVIST_ROLE_ID)]
    message = types.SimpleNamespace(
        author=author,
        channel=channel,
        content='intel',
        attachments=[attachment],
    )

    async def dummy_log(msg, **kwargs):
        return None
    monkeypatch.setattr(main, 'log_action', dummy_log)

    asyncio.run(main.handle_upload(message))
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert (tmp_path / 'intel' / 'report.json').exists()
    assert channel.messages == [' Added `report` to `intel`.']


def test_handle_upload_runs_file_ops_in_thread(tmp_path, monkeypatch):
    monkeypatch.setenv('DISCORD_TOKEN', 'x')
    monkeypatch.setenv('GUILD_ID', '1')
    monkeypatch.setenv('MENU_CHANNEL_ID', '1')
    main = importlib.reload(importlib.import_module('main'))
    monkeypatch.setattr(utils, 'DOSSIERS_DIR', tmp_path)
    monkeypatch.setattr(main, 'DOSSIERS_DIR', tmp_path)
    (tmp_path / 'intel').mkdir()

    channel = DummyChannel(main.UPLOAD_CHANNEL_ID)
    attachment = DummyAttachment('report.json', '{}')
    author = DummyAuthor()
    author.roles = [types.SimpleNamespace(id=main.ARCHIVIST_ROLE_ID)]
    message = types.SimpleNamespace(
        author=author,
        channel=channel,
        content='intel',
        attachments=[attachment],
    )

    main_thread = threading.get_ident()
    called = {}

    def fake_create(category, item_rel_input, data, prefer_txt_default=True):
        called['thread'] = threading.get_ident()
        time.sleep(0.01)
        return os.path.join('intel', 'report.json')

    monkeypatch.setattr(archivist, 'create_dossier_file', fake_create)

    async def dummy_log(msg, **kwargs):
        return None
    monkeypatch.setattr(main, 'log_action', dummy_log)

    asyncio.run(main.handle_upload(message))
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert called['thread'] != main_thread
