import asyncio
import types

import nextcord
import moderation
import main


def test_report_modal_sends_to_channel(monkeypatch):
    logs = []

    async def fake_log_action(message: str, *, broadcast: bool = True):
        logs.append(message)

    monkeypatch.setattr(main, "log_action", fake_log_action)
    monkeypatch.setattr(main, "REPORT_CHANNEL_ID", 0)

    channel_messages = []

    class DummyChannel:
        async def send(self, content, *, embed=None, flags=None):
            channel_messages.append((content, embed, flags))

    dummy_channel = DummyChannel()

    class DummyClient:
        def get_channel(self, cid):
            assert cid == 0
            return dummy_channel

    class DummyResponse:
        def __init__(self):
            self.messages = []

        async def send_message(self, content, *, ephemeral: bool = False):
            self.messages.append((content, ephemeral))

    dummy_message = types.SimpleNamespace(
        content="bad message",
        id=123,
        author=types.SimpleNamespace(mention="@offender"),
        channel=types.SimpleNamespace(mention="#general"),
        jump_url="http://example.com",
    )

    interaction = types.SimpleNamespace(
        user=types.SimpleNamespace(mention="@reporter"),
        client=DummyClient(),
        response=DummyResponse(),
    )

    loop = asyncio.new_event_loop()
    try:
        async def run():
            modal = moderation.ReportModal(dummy_message)
            modal.reason = types.SimpleNamespace(value="spam")
            await modal.callback(interaction)

        loop.run_until_complete(run())
    finally:
        loop.close()

    assert channel_messages, "channel.send not called"
    content, embed, flags = channel_messages[0]
    assert content == "@everyone"
    assert embed is not None
    assert isinstance(flags, nextcord.MessageFlags) and flags.suppress_notifications
    assert any(field.name == "Reason" and field.value == "spam" for field in embed.fields)
    assert interaction.response.messages[0] == ("Report submitted.", True)
    assert logs, "log_action not called"

