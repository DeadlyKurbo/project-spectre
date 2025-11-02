"""Owner portal state management helpers.

This module centralises logic for loading and updating the landing page
broadcast that the owner can curate.  Data is persisted using the
``storage_spaces`` abstraction so it transparently works with either the
object storage backend or the local filesystem fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple

from storage_spaces import read_json, write_json


# Discord user ID that is treated as the canonical owner.  Only this user may
# promote additional managers.
OWNER_USER_ID = "1059522006602752150"

_SETTINGS_KEY = "owner/portal-settings.json"


@dataclass(slots=True)
class OwnerSettings:
    """Strongly-typed representation of the owner broadcast payload."""

    bot_version: str
    latest_update: str
    managers: list[str]

    def copy(self) -> "OwnerSettings":
        return OwnerSettings(
            bot_version=self.bot_version,
            latest_update=self.latest_update,
            managers=list(self.managers),
        )


_DEFAULT_SETTINGS = OwnerSettings(bot_version="", latest_update="", managers=[])


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
    managers_raw = data.get("managers")
    managers = _normalise_manager_ids(managers_raw or [])

    return OwnerSettings(bot_version=bot_version, latest_update=latest_update, managers=managers)


def load_owner_settings(*, with_etag: bool = False) -> Tuple[OwnerSettings, str | None]:
    """Load owner broadcast settings from storage.

    When ``with_etag`` is true the returned tuple also includes the ETag used
    for optimistic concurrency control.
    """

    etag: str | None = None
    if with_etag:
        data, etag = read_json(_SETTINGS_KEY, with_etag=True)
    else:
        try:
            data = read_json(_SETTINGS_KEY)
        except FileNotFoundError:
            data = None

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
        "managers": _normalise_manager_ids(settings.managers),
    }
    return write_json(_SETTINGS_KEY, payload, etag=etag)


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
