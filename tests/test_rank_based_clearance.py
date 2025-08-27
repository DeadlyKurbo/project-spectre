import importlib
import asyncio
from types import SimpleNamespace


def test_create_id_rank_sets_clearance(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    constants = importlib.reload(importlib.import_module("constants"))
    op_login = importlib.reload(importlib.import_module("operator_login"))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    main = importlib.reload(importlib.import_module("main"))

    class DummyRankRole:
        id = constants.CAPTAIN_ROLE_ID

    class DummyMember:
        id = 321
        roles = [DummyRankRole()]

    async def dummy_start_registration(*args, **kwargs):
        return None

    monkeypatch.setattr(main, "start_registration", dummy_start_registration)

    async def dummy_send_message(*args, **kwargs):
        return None

    interaction = SimpleNamespace(
        user=DummyMember(),
        response=SimpleNamespace(send_message=dummy_send_message),
        followup=SimpleNamespace(),
    )

    asyncio.run(main.create_id(interaction))
    asyncio.set_event_loop(asyncio.new_event_loop())

    op = op_login.get_or_create_operator(interaction.user.id)
    assert op.clearance == 5

