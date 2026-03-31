"""Owner portal state management helpers.

This module centralises logic for loading and updating the landing page
broadcast that the owner can curate. Data is persisted using the
``storage_spaces`` abstraction so it transparently works with either the
object storage backend or the local filesystem fallback.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Tuple

from storage_spaces import read_json, write_json

logger = logging.getLogger(__name__)


# Discord user ID that is treated as the canonical owner.  Only this user may
# promote additional managers.
OWNER_USER_KEY = "1059522006602752150"

# Backwards compatibility: retain the previous constant name used by callers.
OWNER_USER_ID = OWNER_USER_KEY

OWNER_SETTINGS_KEY = "owner/portal-settings.json"
_CHANGE_LOG_LIMIT = 100
BROADCAST_PRIORITIES = {"standard", "high-priority", "emergency"}


@dataclass(slots=True)
class ModerationSettings:
    """Configuration toggles for the owner's moderation controls."""

    auto_moderation: bool = True
    link_blocking: bool = False
    new_member_lock: bool = False
    escalation_mode: bool = False

    def copy(self) -> "ModerationSettings":
        return ModerationSettings(
            auto_moderation=self.auto_moderation,
            link_blocking=self.link_blocking,
            new_member_lock=self.new_member_lock,
            escalation_mode=self.escalation_mode,
        )

    def to_payload(self) -> dict[str, bool]:
        return {
            "auto_moderation": bool(self.auto_moderation),
            "link_blocking": bool(self.link_blocking),
            "new_member_lock": bool(self.new_member_lock),
            "escalation_mode": bool(self.escalation_mode),
        }

    @classmethod
    def from_data(cls, value: dict | None) -> "ModerationSettings":
        if not isinstance(value, dict):
            return cls()
        return cls(
            auto_moderation=bool(value.get("auto_moderation", True)),
            link_blocking=bool(value.get("link_blocking", False)),
            new_member_lock=bool(value.get("new_member_lock", False)),
            escalation_mode=bool(value.get("escalation_mode", False)),
        )


@dataclass(slots=True)
class ChangeLogEntry:
    """Represents an audit entry for actions taken in the owner console."""

    timestamp: str
    actor: str
    action: str
    details: str | None = None

    def copy(self) -> "ChangeLogEntry":
        return ChangeLogEntry(
            timestamp=self.timestamp,
            actor=self.actor,
            action=self.action,
            details=self.details,
        )

    def to_payload(self) -> dict[str, str]:
        payload = {
            "timestamp": self.timestamp,
            "actor": self.actor,
            "action": self.action,
        }
        if self.details:
            payload["details"] = self.details
        return payload

    @classmethod
    def from_data(cls, value: dict | None) -> "ChangeLogEntry" | None:
        if not isinstance(value, dict):
            return None
        timestamp = str(value.get("timestamp") or "").strip()
        actor = str(value.get("actor") or "").strip()
        action = str(value.get("action") or "").strip()
        if not timestamp or not actor or not action:
            return None
        details = value.get("details")
        if details is not None:
            details = str(details).strip() or None
        return cls(timestamp=timestamp, actor=actor, action=action, details=details)


@dataclass(slots=True)
class OwnerSettings:
    """Strongly-typed representation of the owner broadcast payload."""

    bot_version: str
    latest_update: str
    managers: list[str]
    fleet_managers: list[str]
    chat_access: list[str]
    bot_active: bool
    moderation: ModerationSettings
    change_log: list[ChangeLogEntry]
    latest_update_priority: str = "standard"

    def copy(self) -> "OwnerSettings":
        return OwnerSettings(
            bot_version=self.bot_version,
            latest_update=self.latest_update,
            managers=list(self.managers),
            fleet_managers=list(self.fleet_managers),
            chat_access=list(self.chat_access),
            bot_active=bool(self.bot_active),
            moderation=self.moderation.copy(),
            change_log=[entry.copy() for entry in self.change_log],
            latest_update_priority=self.latest_update_priority,
        )

    def append_log_entry(self, entry: ChangeLogEntry, *, limit: int = _CHANGE_LOG_LIMIT) -> None:
        """Append ``entry`` while trimming the log to ``limit`` entries."""

        self.change_log.append(entry)
        if limit > 0 and len(self.change_log) > limit:
            # Retain only the newest ``limit`` entries.
            self.change_log = self.change_log[-limit:]


def build_change_entry(actor: str, action: str, details: str | None = None) -> ChangeLogEntry:
    """Create a :class:`ChangeLogEntry` populated with the current timestamp."""

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cleaned_details = details.strip() if isinstance(details, str) else None
    if cleaned_details == "":
        cleaned_details = None
    return ChangeLogEntry(timestamp=timestamp, actor=actor, action=action, details=cleaned_details)


_DEFAULT_SETTINGS = OwnerSettings(
    bot_version="",
    latest_update="",
    latest_update_priority="standard",
    managers=[],
    fleet_managers=[],
    chat_access=[],
    bot_active=True,
    moderation=ModerationSettings(),
    change_log=[],
)


def _normalise_manager_ids(values: Iterable[str]) -> list[str]:
    """Return a sorted, de-duplicated list of Discord IDs as strings."""

    seen: set[str] = set()
    normalised: list[str] = []
    for raw in values:
        if raw is None:
            continue
        value = str(raw).strip()
        if not value or not value.isdigit():
            continue
        if value in seen:
            continue
        seen.add(value)
        normalised.append(value)
    normalised.sort()
    return normalised


def _coerce_settings(data: dict | None) -> OwnerSettings:
    """Convert persisted dictionaries into :class:`OwnerSettings`."""

    if not isinstance(data, dict):
        return _DEFAULT_SETTINGS.copy()

    bot_version = str(data.get("bot_version", "")).strip()
    latest_update = str(data.get("latest_update", "")).strip()
    latest_update_priority = normalise_broadcast_priority(
        data.get("latest_update_priority")
    )
    managers_raw = data.get("managers")
    managers = _normalise_manager_ids(managers_raw or [])
    fleet_managers_raw = data.get("fleet_managers")
    fleet_managers = _normalise_manager_ids(fleet_managers_raw or [])
    chat_access_raw = data.get("chat_access")
    chat_access = _normalise_manager_ids(chat_access_raw or [])
    bot_active = bool(data.get("bot_active", True))
    moderation = ModerationSettings.from_data(data.get("moderation"))

    change_log_entries: list[ChangeLogEntry] = []
    for raw_entry in data.get("change_log") or []:
        entry = ChangeLogEntry.from_data(raw_entry)
        if entry is not None:
            change_log_entries.append(entry)
    if len(change_log_entries) > _CHANGE_LOG_LIMIT:
        change_log_entries = change_log_entries[-_CHANGE_LOG_LIMIT:]

    return OwnerSettings(
        bot_version=bot_version,
        latest_update=latest_update,
        latest_update_priority=latest_update_priority,
        managers=managers,
        fleet_managers=fleet_managers,
        chat_access=chat_access,
        bot_active=bot_active,
        moderation=moderation,
        change_log=change_log_entries,
    )


def load_owner_settings(*, with_etag: bool = False) -> Tuple[OwnerSettings, str | None]:
    """Load owner broadcast settings from storage.

    When ``with_etag`` is true the returned tuple also includes the ETag used
    for optimistic concurrency control.
    """

    etag: str | None = None
    data = None

    try:
        if with_etag:
            data, etag = read_json(OWNER_SETTINGS_KEY, with_etag=True)
        else:
            try:
                data = read_json(OWNER_SETTINGS_KEY)
            except FileNotFoundError:
                data = None
    except json.JSONDecodeError:
        logger.exception(
            "Owner portal settings at %s are not valid JSON; using defaults.",
            OWNER_SETTINGS_KEY,
        )
        data = None
        etag = None
    except Exception:
        logger.exception(
            "Failed to read owner portal settings from %s; using defaults.",
            OWNER_SETTINGS_KEY,
        )
        data = None
        etag = None

    if data is None:
        settings = _DEFAULT_SETTINGS.copy()
    else:
        settings = _coerce_settings(data)

    return settings, etag


def save_owner_settings(settings: OwnerSettings, *, etag: str | None = None) -> bool:
    """Persist ``settings`` to storage.

    Returns ``True`` if the write succeeded.  When an ``etag`` is provided the
    update is only applied if the stored document matches the supplied ETag.
    """

    payload = {
        "bot_version": settings.bot_version.strip(),
        "latest_update": settings.latest_update.strip(),
        "latest_update_priority": normalise_broadcast_priority(
            settings.latest_update_priority
        ),
        "managers": _normalise_manager_ids(settings.managers),
        "fleet_managers": _normalise_manager_ids(settings.fleet_managers),
        "chat_access": _normalise_manager_ids(settings.chat_access),
        "bot_active": bool(settings.bot_active),
        "moderation": settings.moderation.to_payload(),
        "change_log": [entry.to_payload() for entry in settings.change_log[-_CHANGE_LOG_LIMIT:]],
    }
    return write_json(OWNER_SETTINGS_KEY, payload, etag=etag)


def normalise_broadcast_priority(value: str | None) -> str:
    """Return a supported broadcast priority label.

    Unknown values default to ``"standard"`` so legacy payloads remain valid.
    """

    if not isinstance(value, str):
        return "standard"
    candidate = value.strip().lower()
    return candidate if candidate in BROADCAST_PRIORITIES else "standard"


def set_operations_broadcast(
    message: str, *, priority: str, actor: str | None = None
) -> OwnerSettings:
    """Persist the operations broadcast message and priority.

    The change is appended to the owner change log to keep the broadcast
    history aligned with the director console, and the updated settings are
    returned to callers.
    """

    settings, etag = load_owner_settings(with_etag=True)
    cleaned_message = str(message or "").strip()
    cleaned_priority = normalise_broadcast_priority(priority)
    change_entry = build_change_entry(
        actor or "Unknown operator",
        "Operations broadcast updated",
        f"{cleaned_priority} broadcast".replace("-", " "),
    )

    updated = settings.copy()
    updated.latest_update = cleaned_message
    updated.latest_update_priority = cleaned_priority
    updated.append_log_entry(change_entry)

    if save_owner_settings(updated, etag=etag):
        return updated

    refreshed, refreshed_etag = load_owner_settings(with_etag=True)
    refreshed.latest_update = cleaned_message
    refreshed.latest_update_priority = cleaned_priority
    refreshed.append_log_entry(change_entry)
    save_owner_settings(refreshed, etag=refreshed_etag)
    return refreshed


def can_manage_portal(user_id: str | int | None, managers: Iterable[str] | None = None) -> bool:
    """Return ``True`` when ``user_id`` may access the owner portal."""

    if user_id is None:
        return False
    candidate = str(user_id)
    if candidate == OWNER_USER_ID:
        return True
    if managers is None:
        settings, _etag = load_owner_settings()
        managers = settings.managers
    return candidate in set(str(m) for m in managers)


def can_manage_fleet(
    user_id: str | int | None,
    managers: Iterable[str] | None = None,
    fleet_managers: Iterable[str] | None = None,
) -> bool:
    """Return ``True`` if ``user_id`` may manage the fleet manifest."""

    if can_manage_portal(user_id, managers):
        return True
    if user_id is None:
        return False
    candidate = str(user_id)
    if fleet_managers is None:
        settings, _etag = load_owner_settings()
        fleet_managers = settings.fleet_managers
    return candidate in set(str(mid) for mid in fleet_managers)


def can_manage_chat_access(
    user_id: str | int | None, managers: Iterable[str] | None = None
) -> bool:
    """Return ``True`` when ``user_id`` may approve chat access requests."""

    return can_manage_portal(user_id, managers)


def can_access_chat(
    user_id: str | int | None,
    managers: Iterable[str] | None = None,
    chat_access: Iterable[str] | None = None,
) -> bool:
    """Return ``True`` if ``user_id`` may use the A.L.I.C.E. chat relay."""

    if is_owner(user_id):
        return True
    if user_id is None:
        return False
    candidate = str(user_id)
    if managers is not None and candidate in set(str(mid) for mid in managers):
        return True
    if chat_access is None or managers is None:
        settings, _etag = load_owner_settings()
        chat_access = settings.chat_access
        managers = settings.managers
    return candidate in set(str(uid) for uid in chat_access)


def is_owner(user_id: str | int | None) -> bool:
    """Convenience helper for comparing against :data:`OWNER_USER_ID`."""

    return user_id is not None and str(user_id) == OWNER_USER_ID


def validate_discord_id(value: str | None) -> str | None:
    """Return the cleaned Discord ID or ``None`` when invalid."""

    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or not cleaned.isdigit():
        return None
    return cleaned
