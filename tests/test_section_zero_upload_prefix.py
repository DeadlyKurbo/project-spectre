import asyncio
import archivist
import storage_spaces
import main


def test_section_zero_upload_uses_prefix(tmp_path, monkeypatch):
    def _root():
        return str(tmp_path / storage_spaces.get_root_prefix())

    monkeypatch.setattr(storage_spaces, "_local_root", _root)
    async def dummy_log(msg):
        pass
    monkeypatch.setattr(main, "log_action", dummy_log)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def setup():
        with storage_spaces.using_root_prefix("section_zero"):
            view = archivist.UploadFileView()
            modal = archivist.UploadDetailsModal(view, item_rel="ghost")
            upload_view = archivist.UploadMoreView(modal)
        return view, modal, upload_view

    view, modal, upload_view = loop.run_until_complete(setup())

    view.category = "intel"
    view.role_id = 1
    modal.pages = ["classified"]

    class DummyResponse:
        def __init__(self):
            self.kwargs = None
        async def send_message(self, *args, **kwargs):
            self.kwargs = kwargs
    class DummyUser:
        mention = "<@1>"
    class DummyInteraction:
        def __init__(self):
            self.user = DummyUser()
            self.response = DummyResponse()
    inter = DummyInteraction()

    loop.run_until_complete(upload_view.finish(inter))
    loop.close()
    asyncio.set_event_loop(None)

    zero_path = tmp_path / "section_zero" / "intel" / "ghost.txt"
    assert zero_path.read_text() == "classified"
    assert not (tmp_path / "dossiers" / "intel" / "ghost.txt").exists()
