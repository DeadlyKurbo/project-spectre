import asyncio
from types import SimpleNamespace


def test_forgot_password_sends_dm(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    import importlib
    views = importlib.reload(importlib.import_module("views"))
    operator_login = importlib.reload(importlib.import_module("operator_login"))

    sent_messages = []

    class DummyMember:
        id = 123

        async def send(self, content=None, embed=None, view=None):
            sent_messages.append({"content": content, "embed": embed, "view": view})
            return SimpleNamespace()

    member = DummyMember()
    operator_login.get_or_create_operator(member.id)

    response_log = {}

    async def send_message(content, ephemeral=True):
        response_log["content"] = content

    interaction = SimpleNamespace(
        user=member,
        response=SimpleNamespace(send_message=send_message),
        followup=SimpleNamespace(send=lambda *a, **k: None),
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def build_and_run():
        rv = views.RootView()
        await rv.handle_forgot(interaction)

    loop.run_until_complete(build_and_run())
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert "Check your DMs" in response_log["content"]
    assert sent_messages, "DM was not sent"
    view = sent_messages[0]["view"]
    assert view is not None
    labels = [child.label for child in view.children]
    assert "Reset Password" in labels
