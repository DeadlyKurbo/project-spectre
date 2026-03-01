"""Utilities for configuring and reporting scheduled bot restarts."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("spectre")

_DEFAULT_RESTART_DAYS = 7.0
_RESTART_INTERVAL_ENV = "SPECTRE_AUTO_RESTART_DAYS"
_STATE_FILE_ENV = "SPECTRE_RESTART_STATE_FILE"
_DEFAULT_STATE_FILE = Path("Temp") / "bot_restart_state.json"


@dataclass(frozen=True)
class RestartSchedule:
    """Represents the current automatic restart schedule."""

    interval: timedelta

    @property
    def interval_days(self) -> float:
        return self.interval.total_seconds() / 86_400.0


def _parse_days(raw: str | None) -> float | None:
    if raw is None:
        return _DEFAULT_RESTART_DAYS

    text = raw.strip()
    if not text:
        return _DEFAULT_RESTART_DAYS

    lowered = text.lower()
    if lowered in {"0", "off", "false", "disabled", "none"}:
        return None

    try:
        days = float(text)
    except ValueError:
        logger.warning(
            "Invalid %s=%r; defaulting to %.1f days",
            _RESTART_INTERVAL_ENV,
            raw,
            _DEFAULT_RESTART_DAYS,
        )
        return _DEFAULT_RESTART_DAYS

    if days <= 0:
        return None
    return days


def get_restart_schedule() -> RestartSchedule | None:
    """Return the configured restart schedule, or ``None`` when disabled."""

    days = _parse_days(os.getenv(_RESTART_INTERVAL_ENV))
    if days is None:
        return None
    return RestartSchedule(interval=timedelta(days=days))


def compute_next_restart(started_at: datetime, schedule: RestartSchedule | None) -> datetime | None:
    """Compute next restart timestamp for a process started at ``started_at``."""

    if schedule is None:
        return None
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return started_at + schedule.interval


def _state_file_path() -> Path:
    configured = os.getenv(_STATE_FILE_ENV)
    if configured and configured.strip():
        return Path(configured.strip())
    return _DEFAULT_STATE_FILE


def _to_iso8601(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _from_iso8601(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def write_restart_state(*, started_at: datetime, next_restart_at: datetime | None) -> None:
    """Persist restart metadata for dashboard/status reporting."""

    payload = {
        "started_at": _to_iso8601(started_at),
        "next_restart_at": _to_iso8601(next_restart_at),
        "updated_at": _to_iso8601(datetime.now(timezone.utc)),
    }

    path = _state_file_path()
    target_path = path
    try:
        parent = path.parent
        if parent.exists() and not parent.is_dir():
            logger.warning(
                "Restart state directory path is a file (%s); falling back to current directory",
                parent,
            )
            target_path = Path(path.name)
        else:
            parent.mkdir(parents=True, exist_ok=True)

        target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        logger.exception("Failed to write restart state file at %s", target_path)


def read_restart_state() -> dict[str, Any] | None:
    """Load persisted restart metadata written by the bot runtime."""

    path = _state_file_path()
    if not path.exists():
        return None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to read restart state file at %s", path)
        return None

    if not isinstance(raw, dict):
        return None

    started_at = _from_iso8601(raw.get("started_at"))
    next_restart_at = _from_iso8601(raw.get("next_restart_at"))
    updated_at = _from_iso8601(raw.get("updated_at"))
    return {
        "started_at": started_at,
        "next_restart_at": next_restart_at,
        "updated_at": updated_at,
    }
