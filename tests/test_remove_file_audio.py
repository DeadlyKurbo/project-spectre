import asyncio

import utils
from constants import PAGE_SEPARATOR
from dossier import attach_dossier_audio, create_dossier_file, remove_dossier_audio
from spectre.commands import dossier_images as mod


def test_remove_audio_from_page(tmp_path):
    utils.DOSSIERS_DIR = tmp_path
    content = "Page1" + PAGE_SEPARATOR + "Page2"
    create_dossier_file("intel", "report.txt", content)
    attach_dossier_audio("intel", "report", 1, "https://example.com/ambient.mp3")
    remove_dossier_audio("intel", "report", 1)
    data = (tmp_path / "intel" / "report.txt").read_text()
    p1, p2 = data.split(PAGE_SEPARATOR)
    assert "[AUDIO]:" not in p1
    assert p1.strip() == "Page1"
    assert p2.strip() == "Page2"


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


class DummyInteraction:
    user = DummyUser()
    response = DummyResponse()
    followup = DummyFollowup()
    guild = None


def test_remove_file_audio_command(monkeypatch):
    recorded = {}

    async def fake_run_blocking(func, *args):
        recorded["func"] = func
        recorded["args"] = args

    monkeypatch.setattr(mod, "run_blocking", fake_run_blocking)
    monkeypatch.setattr(mod, "guild_id_from_interaction", lambda _i: None)

    async def run():
        import archivist

        monkeypatch.setattr(archivist, "_is_archivist", lambda *_args, **_kwargs: True)
        await mod.remove_file_audio_command(
            DummyContext(), DummyInteraction(), "intel", "report", 2
        )

    asyncio.run(run())

    assert recorded["func"] is mod.remove_dossier_audio
    assert recorded["args"] == ("intel", "report", 2, None)
