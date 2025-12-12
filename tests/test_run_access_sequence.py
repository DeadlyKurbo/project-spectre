import asyncio
from types import SimpleNamespace


def test_run_access_sequence_denied_includes_request(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_ID", "1")
    monkeypatch.setenv("MENU_CHANNEL_ID", "1")

    # Avoid delays during test
    async def dummy_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(asyncio, "sleep", dummy_sleep)

    edits = []

    class DummyMsg:
        async def edit(self, *, content=None, view=None):
            edits.append((content, view))

    async def send_message(content, ephemeral=True):
        return DummyMsg()

    interaction = SimpleNamespace(
        response=SimpleNamespace(send_message=lambda *a, **k: None),
        followup=SimpleNamespace(send=send_message),
    )

    import views

    asyncio.run(
        views.run_access_sequence(
            interaction,
            authorized=False,
            case_ref="FDD-SC-840",
            use_followup=True,
            request_view="view",
        )
    )
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert edits, "message.edit was not called"
    content, view = edits[-1]
    assert "Would you like to request access to this file?" in content
    assert view == "view"

