import asyncio
import types
import os
import nextcord

os.environ.setdefault("GUILD_ID", "0")

from archivist import ReportReplyActionsView
import main


def test_acknowledge_closes_case(monkeypatch):
    logs = []

    async def fake_log_action(message: str, *, broadcast: bool = True):
        logs.append(message)

    monkeypatch.setattr(main, "log_action", fake_log_action)

    embed = nextcord.Embed(
        title="Lead Archivist Signal — 🧭 Test [INFO]", color=0x3B82F6
    )

    class DummyMessage:
        def __init__(self, embed):
            self.embeds = [embed]
            self.edits = []

        async def edit(self, *, embed=None, view=None):
            self.edits.append((embed, view))

    class DummyResponse:
        def __init__(self):
            self.messages = []

        async def send_message(self, content: str, *, ephemeral: bool = False):
            self.messages.append((content, ephemeral))

    message = DummyMessage(embed)
    interaction = types.SimpleNamespace(
        user=types.SimpleNamespace(mention="@user"),
        message=message,
        response=DummyResponse(),
    )

    loop = asyncio.new_event_loop()
    try:
        async def run_test():
            view = ReportReplyActionsView("case_url")
            await view.acknowledge(interaction)
            return view

        view = loop.run_until_complete(run_test())
    finally:
        loop.close()

    assert logs, "log_action was not called"
    new_embed, new_view = message.edits[0]
    assert new_embed.color.value == 0x22C55E
    assert new_embed.title.endswith("[ACK]")
    assert all(item.disabled for item in new_view.children)
    assert interaction.response.messages[0] == ("Acknowledged.", True)


def test_reply_button_present():
    loop = asyncio.new_event_loop()
    try:
        async def create_view():
            return ReportReplyActionsView("case_url")

        view = loop.run_until_complete(create_view())
    finally:
        loop.close()
    labels = [item.label for item in view.children]
    assert "Reply" in labels
    assert "Clarify" not in labels
    assert "Open Case" not in labels
