import asyncio
from types import SimpleNamespace


def test_login_session_caches_password(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    import importlib
    operator_login = importlib.reload(importlib.import_module("operator_login"))
    views = importlib.reload(importlib.import_module("views"))

    current_time = [1000.0]

    def fake_time():
        return current_time[0]

    monkeypatch.setattr(operator_login.time, "time", fake_time)

    op = operator_login.get_or_create_operator(42)
    operator_login.set_password(op.user_id, "pw")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def make_view():
        return views.RootView()

    rv = loop.run_until_complete(make_view())

    modal_log = {}

    async def send_modal(modal):
        modal_log["modal"] = modal

    interaction1 = SimpleNamespace(
        user=SimpleNamespace(id=op.user_id, roles=[]),
        response=SimpleNamespace(send_modal=send_modal),
        followup=SimpleNamespace(send_modal=send_modal),
    )

    loop.run_until_complete(rv.handle_login(interaction1))
    loop.run_until_complete(asyncio.sleep(0))

    assert "modal" in modal_log

    success, locked = operator_login.verify_password(op.user_id, "pw")
    assert success and not locked

    modal_log.clear()
    sent = {}

    async def send_message(embed=None, view=None, ephemeral=True):
        sent["embed"] = embed
        sent["view"] = view

    interaction2 = SimpleNamespace(
        user=SimpleNamespace(id=op.user_id, roles=[]),
        response=SimpleNamespace(send_message=send_message, send_modal=send_modal),
        followup=SimpleNamespace(send_modal=send_modal),
    )

    loop.run_until_complete(rv.handle_login(interaction2))
    loop.run_until_complete(asyncio.sleep(0))

    assert not modal_log
    assert sent["embed"] is not None
    assert sent["view"] is not None

    current_time[0] += 1801

    modal_log2 = {}

    async def send_modal2(modal):
        modal_log2["modal"] = modal

    interaction3 = SimpleNamespace(
        user=SimpleNamespace(id=op.user_id, roles=[]),
        response=SimpleNamespace(send_modal=send_modal2),
        followup=SimpleNamespace(send_modal=send_modal2),
    )

    loop.run_until_complete(rv.handle_login(interaction3))
    loop.run_until_complete(asyncio.sleep(0))

    assert "modal" in modal_log2

    loop.close()
    asyncio.set_event_loop(asyncio.new_event_loop())

