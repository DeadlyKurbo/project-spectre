import importlib
import asyncio
from types import SimpleNamespace


def test_classified_bypass_create_id(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    constants = importlib.reload(importlib.import_module("constants"))
    op_login = importlib.reload(importlib.import_module("operator_login"))
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    main = importlib.reload(importlib.import_module("main"))

    class DummyRole:
        id = constants.CLASSIFIED_ROLE_ID

    class DummyMember:
        id = 99
        roles = [DummyRole()]

    captured = {}

    async def dummy_send_message(content, **kwargs):
        captured["content"] = content

    interaction = SimpleNamespace(
        user=DummyMember(),
        response=SimpleNamespace(send_message=dummy_send_message),
        followup=SimpleNamespace(),
    )

    asyncio.run(main.create_id(interaction))
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert "exempt" in captured["content"]
    assert not any(op.user_id == 99 for op in op_login.list_operators())


def test_show_id_redacted_for_classified(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    constants = importlib.reload(importlib.import_module("constants"))
    importlib.reload(importlib.import_module("operator_login"))
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    main = importlib.reload(importlib.import_module("main"))

    class DummyRole:
        id = constants.CLASSIFIED_ROLE_ID

    class DummyMember:
        id = 100
        roles = [DummyRole()]

    captured = {}

    async def dummy_send_message(content, **kwargs):
        captured["content"] = content

    interaction = SimpleNamespace(
        user=DummyMember(),
        response=SimpleNamespace(send_message=dummy_send_message),
        followup=SimpleNamespace(),
        guild=SimpleNamespace(),
    )

    asyncio.run(main.show_id(interaction))
    asyncio.set_event_loop(asyncio.new_event_loop())

    msg = captured.get("content", "")
    assert msg.count("[REDACTED]") >= 5
