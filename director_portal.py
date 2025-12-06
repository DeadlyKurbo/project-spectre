"""Director console state management helpers.

This module provides persistence helpers for the director console. Broadcasts
are stored via :mod:`storage_spaces` so they can be queried by the web front
end and other services. The API keeps a rolling history to avoid unbounded
storage growth while still providing enough context for operators.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from uuid import uuid4

from storage_spaces import read_json, write_json
from owner_portal import BROADCAST_PRIORITIES, normalise_broadcast_priority


_BROADCAST_KEY = "director/broadcasts.json"
_HISTORY_LIMIT = 50
_ALLOWED_PRIORITIES = BROADCAST_PRIORITIES


@dataclass(slots=True)
class DirectorBroadcast:
    """Represents a single outbound broadcast from the director console."""

    id: str
    created_at: str
    priority: str
    message: str
    actor: str

    def to_payload(self) -> dict[str, str]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "priority": self.priority,
            "message": self.message,
            "actor": self.actor,
        }

    @classmethod
    def from_data(cls, value: dict | None) -> "DirectorBroadcast" | None:
        if not isinstance(value, dict):
            return None

        entry_id = str(value.get("id") or "").strip() or str(uuid4())
        created_at = str(value.get("created_at") or "").strip()
        priority = str(value.get("priority") or "standard").strip().lower()
        message = str(value.get("message") or "").strip()
        actor = str(value.get("actor") or "").strip() or "Unknown operator"

        if priority not in _ALLOWED_PRIORITIES:
            priority = "standard"
        if not created_at:
            created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not message:
            return None

        return cls(
            id=entry_id,
            created_at=created_at,
            priority=priority,
            message=message,
            actor=actor,
        )


def _load_broadcast_entries() -> list[DirectorBroadcast]:
    try:
        data = read_json(_BROADCAST_KEY)
    except FileNotFoundError:
        return []

    entries: list[DirectorBroadcast] = []
    if isinstance(data, dict):
        raw_entries: Iterable[dict] = data.get("entries") or []
    elif isinstance(data, list):
        raw_entries = data
    else:
        raw_entries = []

    for raw in raw_entries:
        entry = DirectorBroadcast.from_data(raw)
        if entry is not None:
            entries.append(entry)
    return entries[-_HISTORY_LIMIT:]


def load_broadcast_history(*, limit: int | None = None) -> list[DirectorBroadcast]:
    """Return the newest broadcast entries, newest last."""

    entries = _load_broadcast_entries()
    if limit is None:
        return entries
    if limit <= 0:
        return []
    return entries[-limit:]


def record_broadcast(message: str, *, priority: str, actor: str) -> DirectorBroadcast:
    """Persist a new broadcast entry and return it."""

    cleaned_message = message.strip()
    if not cleaned_message:
        raise ValueError("message must not be empty")

    normalised_priority = normalise_broadcast_priority(priority)

    entry = DirectorBroadcast(
        id=str(uuid4()),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        priority=normalised_priority,
        message=cleaned_message,
        actor=actor,
    )

    entries = _load_broadcast_entries()
    entries.append(entry)
    payload = {"entries": [item.to_payload() for item in entries[-_HISTORY_LIMIT:]]}
    write_json(_BROADCAST_KEY, payload)
    return entry


__all__ = [
    "DirectorBroadcast",
    "load_broadcast_history",
    "record_broadcast",
]
