from __future__ import annotations

from datetime import datetime, timedelta, timezone

from spectre.restart_policy import (
    compute_next_restart,
    get_restart_schedule,
    read_restart_state,
    write_restart_state,
)


def test_get_restart_schedule_default(monkeypatch):
    monkeypatch.delenv("SPECTRE_AUTO_RESTART_DAYS", raising=False)
    schedule = get_restart_schedule()

    assert schedule is not None
    assert schedule.interval == timedelta(days=7)


def test_get_restart_schedule_disabled(monkeypatch):
    monkeypatch.setenv("SPECTRE_AUTO_RESTART_DAYS", "off")

    assert get_restart_schedule() is None


def test_compute_next_restart():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    schedule = type("Schedule", (), {"interval": timedelta(days=3)})()

    assert compute_next_restart(start, schedule) == datetime(2026, 1, 4, tzinfo=timezone.utc)


def test_restart_state_roundtrip(tmp_path, monkeypatch):
    state_path = tmp_path / "restart-state.json"
    monkeypatch.setenv("SPECTRE_RESTART_STATE_FILE", str(state_path))
    started_at = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
    next_restart = datetime(2026, 2, 8, 12, 0, tzinfo=timezone.utc)

    write_restart_state(started_at=started_at, next_restart_at=next_restart)
    state = read_restart_state()

    assert state is not None
    assert state["started_at"] == started_at
    assert state["next_restart_at"] == next_restart
