import asyncio

from spectre.commands import dossier_images as mod


class DummyResponse:
    async def send_message(self, *args, **kwargs):
        self.sent = (args, kwargs)

    async def defer(self, **kwargs):
        self.deferred = kwargs


class DummyFollowup:
    async def send(self, *args, **kwargs):
        self.sent = (args, kwargs)


class DummyContext:
    async def log_action(self, *args, **kwargs):
        self.logged = (args, kwargs)


class DummyUser:
    mention = "@archivist"


class DummyAttachment:
    content_type = "audio/mpeg"
    proxy_url = "https://proxy.example/voice.mp3"
    url = "https://cdn.example/voice.mp3"


class DummyInteraction:
    user = DummyUser()
    response = DummyResponse()
    followup = DummyFollowup()
    guild = None


def test_set_file_audio_prefers_proxy_url(monkeypatch):
    recorded = {}

    async def fake_run_blocking(func, *args):
        recorded["args"] = args
        return None

    monkeypatch.setattr(mod, "run_blocking", fake_run_blocking)
    monkeypatch.setattr(mod, "guild_id_from_interaction", lambda _i: None)

    async def run():
        import archivist

        monkeypatch.setattr(archivist, "_is_archivist", lambda *_args, **_kwargs: True)
        await mod.set_file_audio_command(
            DummyContext(), DummyInteraction(), "intel", "report", DummyAttachment(), 1
        )

    asyncio.run(run())

    assert recorded["args"][3] == "https://proxy.example/voice.mp3"
