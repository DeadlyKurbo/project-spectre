import importlib
import asyncio
import types

import nextcord


def test_edit_operator_id_modal(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    # Reload modules to pick up patched environment
    importlib.reload(importlib.import_module("constants"))
    op_login = importlib.reload(importlib.import_module("operator_login"))
    archivist = importlib.reload(importlib.import_module("archivist"))

    # Create operator and dummy guild/member
    op = op_login.get_or_create_operator(1)

    class DummyMember:
        def __init__(self, uid, name="User"):
            self.id = uid
            self.display_name = name
            self.roles = []

    class DummyGuild:
        def __init__(self, members):
            self._members = {m.id: m for m in members}

        def get_member(self, uid):
            return self._members.get(uid)

    guild = DummyGuild([DummyMember(op.user_id, "Alpha")])

    loop = asyncio.new_event_loop()
    try:

        async def run_test():
            view = archivist.OperatorIDManagementView([op], guild)
            # Simulate selecting an operator from the dropdown
            async def edit_message(**kwargs):
                pass

            sel_interaction = types.SimpleNamespace(
                data={"values": [str(op.user_id)]},
                response=types.SimpleNamespace(edit_message=edit_message),
            )
            await view.select_operator(sel_interaction)
            assert not view.edit_btn.disabled

            # Capture the modal sent when pressing Edit ID
            captured = []

            async def send_modal(modal):
                captured.append(modal)

            btn_interaction = types.SimpleNamespace(
                response=types.SimpleNamespace(send_modal=send_modal)
            )
            await view.edit_id(btn_interaction)
            assert captured, "send_modal was not called"
            # Ensure modal input is pre-filled with current ID
            assert captured[0].id_input.default_value == op.id_code

        loop.run_until_complete(run_test())
    finally:
        loop.close()
