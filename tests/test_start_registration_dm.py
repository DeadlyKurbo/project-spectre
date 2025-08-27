import asyncio
from types import SimpleNamespace


def test_start_registration_sends_dm(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    import importlib
    views = importlib.reload(importlib.import_module("views"))
    operator_login = importlib.reload(importlib.import_module("operator_login"))

    async def dummy_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(views.asyncio, "sleep", dummy_sleep)

    sent_messages = []

    class DummyChannel:
        async def send(self, *args, **kwargs):
            pass

    class DummyMsg:
        def __init__(self):
            self.edits = []
            self.channel = DummyChannel()

        async def edit(self, **kwargs):
            self.edits.append(kwargs)

    class DummyMember:
        id = 99

        async def send(self, content=None, embed=None, view=None):
            msg = DummyMsg()
            sent_messages.append({"content": content, "embed": embed, "view": view, "msg": msg})
            return msg

    member = DummyMember()
    operator = operator_login.get_or_create_operator(member.id)

    response_log = {}

    async def send_message(content, ephemeral=True):
        response_log["content"] = content

    interaction = SimpleNamespace(
        response=SimpleNamespace(send_message=send_message),
        followup=SimpleNamespace(),
    )

    asyncio.run(views.start_registration(interaction, operator, member))
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert "Check your DMs" in response_log["content"]
    assert sent_messages, "DM was not sent"
    last_edit = sent_messages[0]["msg"].edits[-1]
    embed = last_edit.get("embed")
    view = last_edit.get("view")
    assert embed and embed.title == "[PERSONNEL REGISTRATION TERMINAL]"
    assert view is None
