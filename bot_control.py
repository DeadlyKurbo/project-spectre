"""Director-console control of the Discord bot process.

The website and the bot run as separate processes (see ``railway_entrypoint``),
so they coordinate through two small documents in the persistent store:

* ``system/bot_control.json`` - what the director wants, written by the website.
* ``system/bot_status.json`` - what the bot is doing, a heartbeat written by the bot.

The bot polls the control document and disconnects from Discord when asked to
shut down. The process itself stays alive so it can reconnect when the director
starts it again.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from persistent_store import read_json, save_json

BOT_CONTROL_KEY = "system/bot_control.json"
BOT_STATUS_KEY = "system/bot_status.json"
BOT_CONTROL_POLL_SECONDS = 10
BOT_STATUS_HEARTBEAT_SECONDS = 60
BOT_STATUS_STALE_AFTER = timedelta(seconds=BOT_STATUS_HEARTBEAT_SECONDS * 3)
BOT_CONTROL_REASON_MAX_LENGTH = 300
BOT_CONTROL_ACTIONS = ("start", "stop", "restart")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clean_text(value: Any, limit: int | None = None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    if limit is not None:
        cleaned = cleaned[:limit].rstrip()
    return cleaned or None


def _read(key: str) -> dict[str, Any]:
    try:
        raw = read_json(key)
    except FileNotFoundError:
        return {}
    return raw if isinstance(raw, dict) else {}


def get_bot_control() -> dict[str, Any]:
    """Return the director's requested bot state. Storage errors propagate."""

    raw = _read(BOT_CONTROL_KEY)
    desired = "stopped" if str(raw.get("desired") or "").lower() == "stopped" else "running"
    return {
        "desired": desired,
        "restart_requested_at": _clean_text(raw.get("restart_requested_at")),
        "actor": _clean_text(raw.get("actor")),
        "reason": _clean_text(raw.get("reason"), BOT_CONTROL_REASON_MAX_LENGTH),
        "updated_at": _clean_text(raw.get("updated_at")),
    }


def set_bot_control(action: str, *, actor: str | None = None, reason: str | None = None) -> dict[str, Any]:
    """Record a start, stop or restart request for the bot to pick up."""

    if action not in BOT_CONTROL_ACTIONS:
        raise ValueError(f"Unsupported bot control action: {action!r}")

    current = get_bot_control()
    now = _now()
    payload = {
        "desired": "stopped" if action == "stop" else "running",
        # Full precision so a restart requested within the same second the
        # bot connected still compares as newer than that session.
        "restart_requested_at": now.isoformat() if action == "restart" else current["restart_requested_at"],
        "actor": _clean_text(actor),
        "reason": _clean_text(reason, BOT_CONTROL_REASON_MAX_LENGTH),
        "updated_at": _iso(now),
    }
    save_json(BOT_CONTROL_KEY, payload)
    return payload


def write_bot_status(
    state: str,
    *,
    session_started_at: datetime | None = None,
    latency_ms: int | None = None,
    guild_count: int | None = None,
    bot_user: str | None = None,
) -> None:
    """Publish the bot's heartbeat. Called from the bot process only."""

    save_json(
        BOT_STATUS_KEY,
        {
            "state": state,
            "heartbeat_at": _iso(_now()),
            "session_started_at": _iso(session_started_at) if session_started_at else None,
            "latency_ms": latency_ms,
            "guild_count": guild_count,
            "bot_user": bot_user,
        },
    )


def get_bot_status(*, now: datetime | None = None) -> dict[str, Any]:
    """Return the last heartbeat, with ``state`` set to ``unknown`` once it is stale."""

    raw = _read(BOT_STATUS_KEY)
    heartbeat_at = parse_timestamp(raw.get("heartbeat_at"))
    current = now or _now()
    stale = heartbeat_at is None or current - heartbeat_at > BOT_STATUS_STALE_AFTER
    state = str(raw.get("state") or "").lower()
    if stale or state not in {"online", "connecting", "stopped"}:
        state = "unknown"
    return {
        "state": state,
        "heartbeat_at": _iso(heartbeat_at) if heartbeat_at else None,
        "session_started_at": _clean_text(raw.get("session_started_at")),
        "latency_ms": raw.get("latency_ms") if isinstance(raw.get("latency_ms"), int) else None,
        "guild_count": raw.get("guild_count") if isinstance(raw.get("guild_count"), int) else None,
        "bot_user": _clean_text(raw.get("bot_user")),
    }


def describe_bot_state(control: dict[str, Any], status: dict[str, Any]) -> dict[str, str]:
    """Combine the requested and reported state into a label for the console."""

    desired = control.get("desired")
    state = status.get("state")
    restart_at = parse_timestamp(control.get("restart_requested_at"))
    session_at = parse_timestamp(status.get("session_started_at"))
    restart_pending = bool(restart_at and (session_at is None or restart_at > session_at))

    if desired == "stopped":
        if state in {"online", "connecting"}:
            return {"label": "Shutting down", "tone": "warn", "detail": "Waiting for the bot to disconnect from Discord."}
        if state == "stopped":
            return {"label": "Shut down", "tone": "bad", "detail": "The bot is offline in Discord until it is started again."}
        return {"label": "Shut down", "tone": "bad", "detail": "Shutdown requested. The bot has not reported in recently."}

    if state == "unknown":
        return {
            "label": "No signal",
            "tone": "muted",
            "detail": "The bot has not reported in for a few minutes. It may not be running on this deployment.",
        }
    if restart_pending and state in {"online", "connecting"}:
        return {"label": "Restarting", "tone": "warn", "detail": "Reconnecting to Discord."}
    if state == "stopped":
        return {"label": "Starting", "tone": "warn", "detail": "Start requested. Waiting for the bot to connect."}
    if state == "connecting":
        return {"label": "Connecting", "tone": "warn", "detail": "Connecting to Discord."}
    return {"label": "Online", "tone": "ok", "detail": "Connected to Discord."}


__all__ = [
    "BOT_CONTROL_ACTIONS",
    "BOT_CONTROL_KEY",
    "BOT_CONTROL_POLL_SECONDS",
    "BOT_CONTROL_REASON_MAX_LENGTH",
    "BOT_STATUS_HEARTBEAT_SECONDS",
    "BOT_STATUS_KEY",
    "describe_bot_state",
    "get_bot_control",
    "get_bot_status",
    "parse_timestamp",
    "set_bot_control",
    "write_bot_status",
]
