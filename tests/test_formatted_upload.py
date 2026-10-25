import asyncio
import importlib
import json
import sys
from types import SimpleNamespace


EXPECTED_TEMPLATE = """{
  "file_type": "",
  "subject": "",
  "status": "",
  "clearance": "",
  "last_update": "",
  "file_link": ""
}"""


def _reset_loop():
    asyncio.set_event_loop(asyncio.new_event_loop())


class DummyResponse:
    def __init__(self):
        self.message = None
        self.view = None
        self.modal = None

    async def send_message(self, msg=None, *, ephemeral=False, view=None, embed=None):
        self.message = msg
        self.view = view
        self.embed = embed
        self.ephemeral = ephemeral

    async def send_modal(self, modal):
        self.modal = modal


class DummyUser:
    mention = "<@1>"


def _install_dummy_main(monkeypatch):
    async def dummy_log_action(*args, **kwargs):
        return None

    monkeypatch.setitem(sys.modules, "main", SimpleNamespace(log_action=dummy_log_action))


async def _make_upload_modal(arch, parent):
    return arch.UploadDetailsModal(parent)


def test_formatted_upload_modal_prefills_exact_template(monkeypatch):
    arch = importlib.reload(importlib.import_module("archivist"))
    parent = SimpleNamespace(category="intel", role_id=1, formatted=True)

    modal = asyncio.run(_make_upload_modal(arch, parent))
    _reset_loop()

    assert modal.content.default_value == EXPECTED_TEMPLATE


def test_formatted_upload_uses_json_default(monkeypatch):
    arch = importlib.reload(importlib.import_module("archivist"))
    parent = SimpleNamespace(category="intel", role_id=1, formatted=True, guild_id=None)
    captured = {}

    def fake_create(category, item_rel, content, prefer_txt_default=True, guild_id=None):
        captured["category"] = category
        captured["item_rel"] = item_rel
        captured["content"] = content
        captured["prefer_txt_default"] = prefer_txt_default
        return "key"

    monkeypatch.setattr(arch, "create_dossier_file", fake_create)
    monkeypatch.setattr(arch, "grant_file_clearance", lambda *a, **k: None)
    _install_dummy_main(monkeypatch)

    modal = asyncio.run(_make_upload_modal(arch, parent))
    modal.item = SimpleNamespace(value="formatted report")
    modal.content = SimpleNamespace(value=EXPECTED_TEMPLATE)
    interaction = SimpleNamespace(user=DummyUser(), guild=None, response=DummyResponse())
    asyncio.run(modal.callback(interaction))
    _reset_loop()

    finish = SimpleNamespace(user=DummyUser(), guild=None, response=DummyResponse())
    asyncio.run(interaction.response.view.finish(finish))
    _reset_loop()

    assert captured["item_rel"] == "formatted report"
    assert captured["content"] == EXPECTED_TEMPLATE
    assert captured["prefer_txt_default"] is False
    assert finish.response.message.startswith(" Uploaded")


def test_formatted_upload_link_field_formats_file_link(monkeypatch):
    arch = importlib.reload(importlib.import_module("archivist"))
    parent = SimpleNamespace(category="intel", role_id=1, formatted=True, guild_id=None)
    captured = {}

    def fake_create(category, item_rel, content, prefer_txt_default=True, guild_id=None):
        captured["content"] = content
        return "key"

    monkeypatch.setattr(arch, "create_dossier_file", fake_create)
    monkeypatch.setattr(arch, "grant_file_clearance", lambda *a, **k: None)
    _install_dummy_main(monkeypatch)

    modal = asyncio.run(_make_upload_modal(arch, parent))
    modal.item = SimpleNamespace(value="linked report")
    modal.content = SimpleNamespace(value=EXPECTED_TEMPLATE)
    modal.file_link = SimpleNamespace(value="https://docs.google.com/document/d/example/edit")
    interaction = SimpleNamespace(user=DummyUser(), guild=None, response=DummyResponse())
    asyncio.run(modal.callback(interaction))
    _reset_loop()

    finish = SimpleNamespace(user=DummyUser(), guild=None, response=DummyResponse())
    asyncio.run(interaction.response.view.finish(finish))
    _reset_loop()

    payload = json.loads(captured["content"])
    assert payload["file_link"] == (
        "[Attached File - Open](https://docs.google.com/document/d/example/edit)"
    )


def test_plain_upload_still_uses_txt_default(monkeypatch):
    arch = importlib.reload(importlib.import_module("archivist"))
    parent = SimpleNamespace(category="intel", role_id=1, formatted=False, guild_id=None)
    captured = {}

    def fake_create(category, item_rel, content, prefer_txt_default=True, guild_id=None):
        captured["prefer_txt_default"] = prefer_txt_default
        return "key"

    monkeypatch.setattr(arch, "create_dossier_file", fake_create)
    monkeypatch.setattr(arch, "grant_file_clearance", lambda *a, **k: None)
    _install_dummy_main(monkeypatch)

    modal = asyncio.run(_make_upload_modal(arch, parent))
    modal.item = SimpleNamespace(value="plain report")
    modal.content = SimpleNamespace(value="plain text")
    interaction = SimpleNamespace(user=DummyUser(), guild=None, response=DummyResponse())
    asyncio.run(modal.callback(interaction))
    _reset_loop()

    finish = SimpleNamespace(user=DummyUser(), guild=None, response=DummyResponse())
    asyncio.run(interaction.response.view.finish(finish))
    _reset_loop()

    assert captured["prefer_txt_default"] is True


def test_formatted_upload_rejects_invalid_json(monkeypatch):
    arch = importlib.reload(importlib.import_module("archivist"))
    parent = SimpleNamespace(category="intel", role_id=1, formatted=True, guild_id=None)
    called = False

    def fake_create(*args, **kwargs):
        nonlocal called
        called = True
        return "key"

    monkeypatch.setattr(arch, "create_dossier_file", fake_create)

    modal = asyncio.run(_make_upload_modal(arch, parent))
    modal.item_rel = "bad report"
    modal.pages = ["not-json"]
    finish = SimpleNamespace(user=DummyUser(), guild=None, response=DummyResponse())
    asyncio.run(arch.UploadMoreView(modal).finish(finish))
    _reset_loop()

    assert called is False
    assert "valid JSON" in finish.response.message


def test_formatted_upload_requires_expected_fields(monkeypatch):
    arch = importlib.reload(importlib.import_module("archivist"))
    parent = SimpleNamespace(category="intel", role_id=1, formatted=True, guild_id=None)
    called = False

    def fake_create(*args, **kwargs):
        nonlocal called
        called = True
        return "key"

    monkeypatch.setattr(arch, "create_dossier_file", fake_create)

    modal = asyncio.run(_make_upload_modal(arch, parent))
    modal.item_rel = "bad report"
    modal.pages = ['{"file_type": ""}']
    finish = SimpleNamespace(user=DummyUser(), guild=None, response=DummyResponse())
    asyncio.run(arch.UploadMoreView(modal).finish(finish))
    _reset_loop()

    assert called is False
    assert "subject" in finish.response.message


def test_formatted_upload_menu_scope(monkeypatch):
    arch = importlib.reload(importlib.import_module("archivist"))

    class Perms:
        administrator = False

    class Role:
        def __init__(self, rid):
            self.id = rid

    class Guild:
        owner_id = 2

    class User:
        id = 1
        mention = "<@1>"
        roles = [Role(arch.ARCHIVIST_ROLE_ID)]
        guild_permissions = Perms()
        guild = Guild()

    full_view = arch.FileManagementView(arch.ArchivistConsoleView(User()))
    limited_view = arch.ArchivistLimitedConsoleView(User())
    trainee_view = arch.TraineeTaskSelectView(User())

    assert "Upload Formatted File" in [item.label for item in full_view.children]
    assert "Upload Formatted File" in [item.label for item in limited_view.children]
    assert "Upload Formatted File" not in [item.label for item in trainee_view.children]
