import importlib
import asyncio
from types import SimpleNamespace


def test_show_id_only_shows_invoking_user(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    constants = importlib.reload(importlib.import_module("constants"))
    op_login = importlib.reload(importlib.import_module("operator_login"))
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    main = importlib.reload(importlib.import_module("main"))

    # register two operators
    op_login.set_password(101, "pass1")
    op_login.set_password(102, "pass2")

    class DummyMember:
        def __init__(self, uid):
            self.id = uid
            self.roles = []
            self.mention = f"<@{uid}>"

    member1 = DummyMember(101)
    member2 = DummyMember(102)

    class DummyGuild:
        members = [member1, member2]

        def get_member(self, uid):
            return next((m for m in self.members if m.id == uid), None)

    captured = {}

    async def dummy_send_message(content, **kwargs):
        captured["content"] = content
        captured.update(kwargs)

    interaction = SimpleNamespace(
        user=member1,
        guild=DummyGuild(),
        response=SimpleNamespace(send_message=dummy_send_message),
        followup=SimpleNamespace(),
    )

    asyncio.run(main.show_id(interaction))
    asyncio.set_event_loop(asyncio.new_event_loop())

    msg = captured.get("content", "")
    assert member1.mention in msg
    assert member2.mention not in msg
    assert not captured.get("ephemeral")
