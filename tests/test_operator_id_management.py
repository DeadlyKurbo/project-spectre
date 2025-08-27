import importlib
import asyncio
from types import SimpleNamespace


def test_update_and_delete_operator(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    # Reload modules to apply new environment variables
    constants = importlib.reload(importlib.import_module("constants"))
    op_login = importlib.reload(importlib.import_module("operator_login"))

    op = op_login.get_or_create_operator(42)
    original = op.id_code
    op_login.update_id_code(42, "GU7-OPR-0001-AA")
    assert op_login.get_or_create_operator(42).id_code == "GU7-OPR-0001-AA"
    assert op_login.list_operators()
    op_login.delete_operator(42)
    assert all(r.user_id != 42 for r in op_login.list_operators())
    # Ensure original ID can be recreated
    op2 = op_login.get_or_create_operator(42)
    assert op2.id_code != "GU7-OPR-0001-AA"


def test_update_id_code_ignores_none(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    importlib.reload(importlib.import_module("constants"))
    op_login = importlib.reload(importlib.import_module("operator_login"))

    op = op_login.get_or_create_operator(1)
    original = op.id_code
    op_login.update_id_code(1, None)
    assert op_login.get_or_create_operator(1).id_code == original


def test_edit_id_modal_opens(monkeypatch, tmp_path):
    """Pressing the Edit ID button should display a pre-filled modal."""
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    importlib.reload(importlib.import_module("constants"))
    op_login = importlib.reload(importlib.import_module("operator_login"))
    arch = importlib.reload(importlib.import_module("archivist"))

    async def run():
        op = op_login.get_or_create_operator(7)
        guild = SimpleNamespace(get_member=lambda uid: None)
        view = arch.OperatorIDManagementView([op], guild)

        class DummyResponse:
            def __init__(self):
                self.modal = None

            async def edit_message(self, **kwargs):
                pass

            async def send_modal(self, modal):
                self.modal = modal

        inter = SimpleNamespace(
            data={"values": [str(op.user_id)]}, response=DummyResponse()
        )

        await view.select_operator(inter)
        await view.edit_id(inter)
        return inter.response.modal, op.id_code

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    modal, code = loop.run_until_complete(run())
    loop.close()
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert isinstance(modal, arch.EditOperatorIDModal)
    assert modal.id_input.default_value == code
