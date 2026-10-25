import asyncio
import importlib
import sys
import types
from types import SimpleNamespace


def test_help_button_opens_modal(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    views = importlib.reload(importlib.import_module("views"))
    archivist = importlib.reload(importlib.import_module("archivist"))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def build_view():
        return views.RootView()

    rv = loop.run_until_complete(build_view())
    labels = [child.label for child in rv.children]
    assert "Help" in labels

    captured = {}

    async def send_modal(modal):
        captured["modal"] = modal

    interaction = SimpleNamespace(
        user=SimpleNamespace(id=1),
        response=SimpleNamespace(send_modal=send_modal),
    )

    loop.run_until_complete(rv.open_help(interaction))
    loop.close()
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert "modal" in captured
    assert isinstance(captured["modal"], archivist.ReportProblemModal)


def test_report_problem_uses_dashboard_report_channel(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_ROOT_PREFIX", str(tmp_path))
    archivist = importlib.reload(importlib.import_module("archivist"))

    monkeypatch.setattr(
        archivist,
        "get_server_config",
        lambda guild_id: {
            "REPORT_REPLY_CHANNEL_ID": "456",
            "LEAD_ARCHIVIST_ROLE_ID": "789",
        },
    )

    sent = {}

    class _Channel:
        async def send(self, message, view=None):
            sent["message"] = message
            sent["view"] = view

    channel = _Channel()
    guild = SimpleNamespace(id=42, get_channel=lambda channel_id: channel if channel_id == 456 else None)

    async def response_send_message(*args, **kwargs):
        sent["response"] = (args, kwargs)

    interaction = SimpleNamespace(
        user=SimpleNamespace(id=1, mention="<@1>"),
        guild=guild,
        client=SimpleNamespace(fetch_channel=None),
        response=SimpleNamespace(send_message=response_send_message),
    )

    async def fake_log_action(message):
        sent["log"] = message

    monkeypatch.setitem(sys.modules, "main", types.SimpleNamespace(log_action=fake_log_action))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _invoke_modal():
        modal = archivist.ReportProblemModal(interaction.user)
        modal.title_input = SimpleNamespace(value="Need assistance")
        modal.description = SimpleNamespace(value="Help request details")
        await modal.callback(interaction)

    loop.run_until_complete(_invoke_modal())
    loop.close()
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert "PING: <@&789>" in sent["message"]
    assert isinstance(sent["view"], archivist.ReportProblemView)
    assert sent["view"].report_channel_id == 456
    assert sent["response"][1]["ephemeral"] is True
