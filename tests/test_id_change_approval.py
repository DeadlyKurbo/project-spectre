import asyncio
from types import SimpleNamespace


def test_id_change_request_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    import importlib, sys, types
    operator_login = importlib.reload(importlib.import_module("operator_login"))
    views = importlib.reload(importlib.import_module("views"))
    archivist = importlib.reload(importlib.import_module("archivist"))

    async def fake_log_action(*args, **kwargs):
        pass
      
    requester = SimpleNamespace(id=1, mention="@user", roles=[])
    operator_login.get_or_create_operator(1)

    async def run():
        modal = views.IdChangeRequestModal("OLD", requester)
        # simulate user input
        monkeypatch.setattr(type(modal.reason), "value", property(lambda self: "NEW"))

        sent = {}

        async def send(content, view=None):
            sent["content"] = content
            sent["view"] = view

        channel = SimpleNamespace(send=send)

        async def send_message(*args, **kwargs):
            pass

        interaction = SimpleNamespace(
            client=SimpleNamespace(get_channel=lambda _id: channel),
            user=requester,
            response=SimpleNamespace(send_message=send_message),
        )

        await modal.callback(interaction)

        # ensure a report view was sent
        view = sent.get("view")
        assert isinstance(view, archivist.ReportProblemView)
        assert "Requested ID: `NEW`" in sent.get("content", "")

    asyncio.run(run())
