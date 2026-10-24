import asyncio
import types
from datetime import datetime, timedelta, timezone

import pytest

import bot_control
import spectre.runtime as runtime_mod


@pytest.fixture
def store(monkeypatch):
    data: dict[str, dict] = {}

    def fake_read(key):
        if key not in data:
            raise FileNotFoundError(key)
        return dict(data[key])

    def fake_save(key, payload):
        data[key] = dict(payload)

    monkeypatch.setattr(bot_control, "read_json", fake_read)
    monkeypatch.setattr(bot_control, "save_json", fake_save)
    return data


def test_bot_control_defaults_to_running(store):
    control = bot_control.get_bot_control()
    assert control["desired"] == "running"
    assert control["restart_requested_at"] is None


def test_set_bot_control_stop_start_restart(store):
    stopped = bot_control.set_bot_control("stop", actor="DK (1)", reason="  hotfix   deploy ")
    assert stopped["desired"] == "stopped"
    assert stopped["reason"] == "hotfix deploy"
    assert bot_control.get_bot_control()["actor"] == "DK (1)"

    started = bot_control.set_bot_control("start", actor="DK (1)")
    assert started["desired"] == "running"
    assert started["restart_requested_at"] is None

    restarted = bot_control.set_bot_control("restart", actor="DK (1)")
    assert restarted["desired"] == "running"
    assert restarted["restart_requested_at"].startswith(restarted["updated_at"][:19])

    with pytest.raises(ValueError):
        bot_control.set_bot_control("explode")


def test_bot_status_goes_unknown_when_heartbeat_is_stale(store):
    bot_control.write_bot_status("online", latency_ms=42, guild_count=3, bot_user="Spectre#0001")
    fresh = bot_control.get_bot_status()
    assert fresh["state"] == "online"
    assert fresh["guild_count"] == 3

    later = datetime.now(timezone.utc) + timedelta(minutes=10)
    assert bot_control.get_bot_status(now=later)["state"] == "unknown"


@pytest.mark.parametrize(
    ("desired", "state", "restart_after_session", "label"),
    [
        ("running", "online", False, "Online"),
        ("running", "connecting", False, "Connecting"),
        ("running", "online", True, "Restarting"),
        ("running", "stopped", False, "Starting"),
        ("running", "unknown", False, "No signal"),
        ("stopped", "online", False, "Shutting down"),
        ("stopped", "stopped", False, "Shut down"),
        ("stopped", "unknown", False, "Shut down"),
    ],
)
def test_describe_bot_state(desired, state, restart_after_session, label):
    session = datetime(2026, 10, 24, 7, 0, tzinfo=timezone.utc)
    restart = session + (timedelta(minutes=5) if restart_after_session else -timedelta(minutes=5))
    control = {"desired": desired, "restart_requested_at": restart.isoformat()}
    status = {"state": state, "session_started_at": session.isoformat()}
    assert bot_control.describe_bot_state(control, status)["label"] == label


class FakeBot:
    instances: list["FakeBot"] = []

    def __init__(self):
        self.started = asyncio.Event()
        self._closed = asyncio.Event()
        self.guilds = [object(), object()]
        self.user = "Spectre#0001"
        self.latency = 0.05
        FakeBot.instances.append(self)

    async def start(self, _token):
        self.started.set()
        await self._closed.wait()

    async def close(self):
        self._closed.set()

    def is_ready(self):
        return self.started.is_set() and not self._closed.is_set()


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()
        self.token = "token"
        self.logger = types.SimpleNamespace(
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            error=lambda *a, **k: None,
            exception=lambda *a, **k: None,
        )


@pytest.fixture
def runtime(monkeypatch):
    FakeBot.instances = []
    control = {"desired": "running", "restart_requested_at": None}
    reports: list[str] = []
    real_sleep = asyncio.sleep

    async def fast_sleep(delay, *args, **kwargs):
        await real_sleep(min(delay, 0.01))

    def fake_get_control():
        if isinstance(control.get("error"), Exception):
            raise control["error"]
        return dict(control)

    async def noop_async():
        return None

    monkeypatch.setattr(runtime_mod, "asyncio", types.SimpleNamespace(**{**vars(asyncio), "sleep": fast_sleep}))
    monkeypatch.setattr(runtime_mod, "get_bot_control", fake_get_control)
    monkeypatch.setattr(runtime_mod, "write_bot_status", lambda state, **_kw: reports.append(state))
    monkeypatch.setattr(runtime_mod, "get_restart_schedule", lambda: None)
    monkeypatch.setattr(runtime_mod, "SpectreApplication", FakeApp)
    monkeypatch.setattr(runtime_mod, "reset_moderation_service", noop_async)
    monkeypatch.setattr(runtime_mod, "prune_archivist_runtime_cache", lambda: None)
    monkeypatch.setattr(runtime_mod, "clear_archivist_runtime_cache", lambda: None)

    rt = runtime_mod.SpectreRuntime.__new__(runtime_mod.SpectreRuntime)
    rt.app = FakeApp()
    rt._shutdown = False
    rt._planned_restart = False
    rt._control_stop = False
    return types.SimpleNamespace(rt=rt, control=control, reports=reports)


async def _wait_for(predicate, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


async def _stop(rt, task):
    rt._shutdown = True
    await rt.app.bot.close()
    await asyncio.wait_for(task, timeout=5)


def test_runtime_shuts_down_and_restarts_on_director_request(runtime):
    async def scenario():
        task = asyncio.create_task(runtime.rt._run_bot())
        await _wait_for(lambda: FakeBot.instances[0].started.is_set())
        await _wait_for(lambda: "online" in runtime.reports)

        runtime.control["desired"] = "stopped"
        await _wait_for(lambda: "stopped" in runtime.reports)
        assert FakeBot.instances[0]._closed.is_set()
        await asyncio.sleep(0.1)
        assert len(FakeBot.instances) == 2
        assert not FakeBot.instances[1].started.is_set()

        runtime.control["desired"] = "running"
        await _wait_for(lambda: FakeBot.instances[1].started.is_set())
        await _stop(runtime.rt, task)

    asyncio.run(scenario())


def test_runtime_restarts_when_requested_after_session_start(runtime):
    async def scenario():
        task = asyncio.create_task(runtime.rt._run_bot())
        await _wait_for(lambda: FakeBot.instances[0].started.is_set())

        runtime.control["restart_requested_at"] = datetime.now(timezone.utc).isoformat()
        await _wait_for(lambda: len(FakeBot.instances) == 2 and FakeBot.instances[1].started.is_set())
        assert FakeBot.instances[0]._closed.is_set()
        await _stop(runtime.rt, task)

    asyncio.run(scenario())


def test_runtime_starts_when_control_state_is_unreadable(runtime):
    runtime.control["error"] = RuntimeError("storage down")

    async def scenario():
        task = asyncio.create_task(runtime.rt._run_bot())
        await _wait_for(lambda: FakeBot.instances[0].started.is_set())
        await asyncio.sleep(0.1)
        assert not FakeBot.instances[0]._closed.is_set()
        await _stop(runtime.rt, task)

    asyncio.run(scenario())
