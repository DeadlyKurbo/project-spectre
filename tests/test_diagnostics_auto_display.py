import types
import asyncio


class DummyResponse:
    async def send_message(self, *args, **kwargs):
        pass


class DummyFollowup:
    def __init__(self):
        self.sent = False

    async def send(self, *args, **kwargs):
        self.sent = True


class DummyMessage:
    async def edit(self, *args, **kwargs):
        pass


class DummyUser:
    def __str__(self):
        return "dummy"


class DummyInteraction:
    def __init__(self):
        self.response = DummyResponse()
        self.followup = DummyFollowup()
        self.message = DummyMessage()
        self.user = DummyUser()


def test_diagnostic_triggers_callback(monkeypatch):
    monkeypatch.setenv("GUILD_ID", "1")
    import views  # import after env setup
    monkeypatch.setattr("views.random.random", lambda: 0.0)
    async def fast_sleep(_):
        pass
    monkeypatch.setattr("views.asyncio.sleep", fast_sleep)

    async def fake_log_action(*args, **kwargs):
        pass

    monkeypatch.setitem(
        __import__("sys").modules,
        "main",
        types.SimpleNamespace(log_action=fake_log_action),
    )

    interaction = DummyInteraction()
    shown = False

    async def on_fix(inter):
        nonlocal shown
        shown = True

    async def run():
        triggered = await views.maybe_system_alert(interaction, on_fix=on_fix)
        assert triggered
        assert shown
        assert interaction.followup.sent

    asyncio.run(run())
    asyncio.set_event_loop(asyncio.new_event_loop())
