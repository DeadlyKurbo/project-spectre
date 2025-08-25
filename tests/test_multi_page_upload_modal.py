import asyncio, types, sys
from constants import CONTENT_MAX_LENGTH, PAGE_SEPARATOR

def test_upload_details_modal_multi_page(monkeypatch):
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")

    import archivist

    parent = types.SimpleNamespace(category="intel", role_id=1)

    async def make_modal():
        return archivist.UploadDetailsModal(parent)

    modal1 = asyncio.run(make_modal())
    modal1.item = types.SimpleNamespace(value="report.txt")
    modal1.content = types.SimpleNamespace(value="a" * CONTENT_MAX_LENGTH, max_length=CONTENT_MAX_LENGTH)

    captured = {}

    def fake_create(category, item_rel, content, prefer_txt_default=True):
        captured["category"] = category
        captured["item_rel"] = item_rel
        captured["content"] = content
        return "key"

    monkeypatch.setattr(archivist, "create_dossier_file", fake_create)
    monkeypatch.setattr(archivist, "grant_file_clearance", lambda *a, **k: None)

    async def dummy_log_action(message, broadcast=True):
        return None

    dummy_main = types.SimpleNamespace(log_action=dummy_log_action)
    monkeypatch.setitem(sys.modules, "main", dummy_main)

    class DummyResponse:
        def __init__(self):
            self.modal = None
            self.message = None
            self.view = None

        async def send_modal(self, modal):
            self.modal = modal

        async def send_message(self, msg, ephemeral=False, view=None):
            self.message = msg
            self.view = view

    class DummyUser:
        mention = "<@1>"

    interaction1 = types.SimpleNamespace(user=DummyUser(), response=DummyResponse())
    asyncio.run(modal1.callback(interaction1))
    asyncio.set_event_loop(asyncio.new_event_loop())

    add_inter = types.SimpleNamespace(user=DummyUser(), response=DummyResponse())
    asyncio.run(interaction1.response.view.add_page(add_inter))
    asyncio.set_event_loop(asyncio.new_event_loop())

    modal2 = add_inter.response.modal
    assert isinstance(modal2, archivist.UploadDetailsModal)

    modal2.content = types.SimpleNamespace(value="b", max_length=CONTENT_MAX_LENGTH)
    interaction2 = types.SimpleNamespace(user=DummyUser(), response=DummyResponse())
    asyncio.run(modal2.callback(interaction2))
    asyncio.set_event_loop(asyncio.new_event_loop())

    finish_inter = types.SimpleNamespace(user=DummyUser(), response=DummyResponse())
    asyncio.run(interaction2.response.view.finish(finish_inter))
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert captured["content"] == PAGE_SEPARATOR.join(["a" * CONTENT_MAX_LENGTH, "b"])
    assert finish_inter.response.message.startswith("✅ Uploaded")
