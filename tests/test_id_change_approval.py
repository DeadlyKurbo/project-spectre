import asyncio
from types import SimpleNamespace

def test_id_change_request_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    import importlib, sys, types
    operator_login = importlib.reload(importlib.import_module("operator_login"))
    views = importlib.reload(importlib.import_module("views"))

    async def fake_log_action(*args, **kwargs):
        pass

    monkeypatch.setitem(
        sys.modules, "main", types.SimpleNamespace(log_action=fake_log_action)
    )

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

        # ensure a decision view was sent
        view = sent.get("view")
        assert isinstance(view, views.IdChangeDecisionView)

        role = SimpleNamespace(id=views.LEAD_ARCHIVIST_ROLE_ID)
        resp = {}

        async def respond(msg):
            resp["msg"] = msg

        async def edit(**kwargs):
            pass

        interaction2 = SimpleNamespace(
            user=SimpleNamespace(mention="@lead", roles=[role], id=2),
            response=SimpleNamespace(send_message=respond),
            message=SimpleNamespace(edit=edit),
        )

        await view.approve(interaction2)
        op = operator_login.get_or_create_operator(1)
        assert op.id_code == "NEW"
        assert "updated" in resp.get("msg", "")

    asyncio.run(run())
