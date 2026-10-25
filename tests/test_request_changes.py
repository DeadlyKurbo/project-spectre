import importlib, asyncio
from types import SimpleNamespace

import utils


async def run_modal_callback(modal, interaction):
    await modal.callback(interaction)


def test_request_changes_keeps_submission_open(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")
    monkeypatch.setattr(utils, "DOSSIERS_DIR", tmp_path)
    arch = importlib.reload(importlib.import_module("archivist"))
    main = importlib.reload(importlib.import_module("main"))

    async def fake_log_action(*args, **kwargs):
        pass

    monkeypatch.setattr(main, "log_action", fake_log_action)

    sub_id = arch._save_submission(
        1,
        {"type": "upload", "category": "intel", "item": "file.txt", "content": "hi"},
    )

    class DummyUser:
        def __init__(self):
            self.sent = None

        async def send(self, msg, file=None):
            self.sent = msg

    test_user = DummyUser()

    class DummyGuild:
        def get_member(self, _):
            return test_user

    class DummyResponse:
        async def send_message(self, *args, **kwargs):
            pass

    class DummyClient:
        async def fetch_user(self, _):
            return test_user

    role = SimpleNamespace(id=arch.LEAD_ARCHIVIST_ROLE_ID)
    inter = SimpleNamespace(
        guild=DummyGuild(),
        response=DummyResponse(),
        client=DummyClient(),
        user=SimpleNamespace(mention="@approver", roles=[role]),
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run():
        view = arch.TraineeSubmissionReviewView(1, sub_id)
        modal = arch.TraineeSubmissionRequestChangesModal(view)
        monkeypatch.setattr(type(modal.reason), "value", property(lambda self: "fix it"))
        await run_modal_callback(modal, inter)

    loop.run_until_complete(run())
    loop.close()
    asyncio.set_event_loop(asyncio.new_event_loop())

    data = arch._load_submission(1, sub_id)
    assert data["status"] == "pending"
    assert data["reason"] == "fix it"
    assert test_user.sent.startswith("")
