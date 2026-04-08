"""Helpers for persisting lightweight configuration.

Configuration values such as the log channel, build version and status message
ID need to persist across bot restarts and, ideally, across deployments.  The
original implementation wrote these settings to a JSON file on the local
filesystem.  That approach works for a single instance but does not propagate to
other nodes and is lost if the container is rebuilt.

To make the configuration truly persistent the data is now stored via the
``persistent_store`` helpers, which use S3-compatible object storage (or local
disk) by default, or a PostgreSQL ``spectre_kv`` table when ``DATABASE_URL`` is
set (Railway and other hosts). The
storage path is governed by
``CONFIG_FILE`` which defaults to ``config/config.json`` relative to the root of
the dossier storage.  If ``CONFIG_FILE`` is set to an absolute path the module
will read and write that local file instead – this behaviour preserves the
ability for tests to override the location with a temporary directory.

All helpers return sensible defaults when the configuration file does not exist
or contains invalid JSON.
"""

import json
import os
from datetime import datetime, timezone

from persistent_store import read_json, save_json

SYSTEM_HEALTH_STATUSES = {
    "online": "Online",
    "maintenance": "Maintenance",
    "degraded": "Degraded",
    "offline": "Offline",
}
_SYSTEM_HEALTH_NOTE_LIMIT = 140
_SYSTEM_HEALTH_DEFAULT_NOTE = "No anomalies detected."
_SITE_LOCK_KEY = "site_lock"
SITE_LOCK_MESSAGE_DEFAULT = (
    "The website is currently experiencing maintenance, please check back in at a later time."
)

# Default path within the dossier storage.  Tests may monkeypatch this to an
# absolute path which forces local file access instead.
CONFIG_FILE = "config/config.json"


def load_config():
    """Return the persisted configuration dictionary.

    When ``CONFIG_FILE`` is an absolute path the function interacts with the
    local filesystem for backwards compatibility with existing tests.  For
    relative paths the file is retrieved via ``persistent_store`` which stores the
    data in the configured persistence backend (object storage or local disk by
    default; PostgreSQL when ``DATABASE_URL`` selects the railway backend).
    """

    # Absolute path -> local filesystem
    if os.path.isabs(CONFIG_FILE):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    return {}
        return {}

    # Relative path -> configured persistence backend
    try:
        return read_json(CONFIG_FILE)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def save_config(data):
    """Persist ``data`` to ``CONFIG_FILE``.

    Uses the configured persistence backend for relative paths so configuration
    survives stateless deploys regardless of storage provider. When ``CONFIG_FILE`` is
    absolute the data is written to the local filesystem instead.  The JSON is
    formatted with ``indent=2`` for easier manual inspection.
    """

    if os.path.isabs(CONFIG_FILE):
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    else:
        save_json(CONFIG_FILE, data)


def _clean_site_lock_message(message: str | None) -> str:
    if message is None:
        return SITE_LOCK_MESSAGE_DEFAULT
    cleaned = " ".join(str(message).splitlines()).strip()
    return cleaned or SITE_LOCK_MESSAGE_DEFAULT


def get_site_lock_state() -> dict:
    """Return the persisted site lock state used for maintenance mode."""

    data = load_config()
    raw = data.get(_SITE_LOCK_KEY)
    if not isinstance(raw, dict):
        return {
            "enabled": False,
            "message": SITE_LOCK_MESSAGE_DEFAULT,
            "actor": None,
            "enabled_at": None,
        }

    enabled = bool(raw.get("enabled"))
    actor = raw.get("actor")
    if actor is not None:
        actor = str(actor).strip() or None
    enabled_at = raw.get("enabled_at")
    if enabled_at is not None:
        enabled_at = str(enabled_at).strip() or None

    return {
        "enabled": enabled,
        "message": _clean_site_lock_message(raw.get("message")),
        "actor": actor,
        "enabled_at": enabled_at,
    }


def set_site_lock_state(
    enabled: bool,
    *,
    actor: str | None = None,
    message: str | None = None,
) -> None:
    """Persist the maintenance lock state."""

    cleaned_actor = str(actor).strip() if actor else None
    payload = {
        "enabled": bool(enabled),
        "message": _clean_site_lock_message(message),
        "actor": cleaned_actor,
        "enabled_at": None,
    }
    if enabled:
        payload["enabled_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    data = load_config()
    data[_SITE_LOCK_KEY] = payload
    save_config(data)


def get_min_account_age_days() -> int | None:
    """Return the minimum account age in days if configured."""

    days = load_config().get("min_account_age_days")
    if days is None:
        return None
    try:
        return int(days)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def set_min_account_age_days(days: int) -> None:
    """Persist the minimum account age requirement in days."""

    data = load_config()
    data["min_account_age_days"] = int(days)
    save_config(data)


def get_build_version(default: str = "v2.3.1") -> str:
    """Return the stored build version or ``default`` if unset."""
    return load_config().get("build_version", default)


def set_build_version(version: str) -> None:
    """Persist ``version`` as the current build version."""
    data = load_config()
    data["build_version"] = version
    save_config(data)


def get_status_message_id() -> int | None:
    """Return the stored archive status message ID if set."""
    msg_id = load_config().get("status_message_id")
    if msg_id is None:
        return None
    try:
        return int(msg_id)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def set_status_message_id(message_id: int) -> None:
    """Persist the archive status message ID."""
    data = load_config()
    data["status_message_id"] = int(message_id)
    save_config(data)


def get_latest_changelog() -> dict | None:
    """Return the most recent changelog entry if available."""
    entry = load_config().get("latest_changelog")
    return entry if isinstance(entry, dict) else None


def set_latest_changelog(entry: dict) -> None:
    """Persist ``entry`` as the latest changelog item."""
    data = load_config()
    data["latest_changelog"] = entry
    save_config(data)


def _coerce_health_state(value):
    if not isinstance(value, dict):
        return None
    status = str(value.get("status") or "").strip().lower()
    if status not in SYSTEM_HEALTH_STATUSES:
        return None
    note = value.get("note")
    note_str = ""
    if note is not None:
        note_str = " ".join(str(note).splitlines()).strip()
    return {"status": status, "note": note_str}


def _format_system_health_summary(status: str, note: str) -> str:
    label = SYSTEM_HEALTH_STATUSES.get(status, status.title() or "Online")
    cleaned_note = note.strip()
    if not cleaned_note and status == "online":
        cleaned_note = _SYSTEM_HEALTH_DEFAULT_NOTE
    return f"{label} — {cleaned_note}" if cleaned_note else label


def get_system_health_state() -> dict[str, str]:
    """Return the structured system health state for the admin console."""

    data = load_config()
    state = _coerce_health_state(data.get("system_health_state"))
    if state:
        return state

    legacy = data.get("system_health")
    if isinstance(legacy, str):
        legacy_note = " ".join(legacy.splitlines()).strip()
        if legacy_note:
            return {"status": "online", "note": legacy_note}

    return {"status": "online", "note": ""}


def get_system_health(
    default: str = "✅ Operational | No anomalies detected",
) -> str:
    """Return the configured system health string."""

    data = load_config()
    state = _coerce_health_state(data.get("system_health_state"))
    if state:
        return _format_system_health_summary(state["status"], state.get("note", ""))

    legacy = data.get("system_health")
    if isinstance(legacy, str):
        legacy_value = legacy.strip()
        if legacy_value:
            return legacy_value

    return default


def set_system_health(status: str) -> None:
    """Persist the current system health string."""

    data = load_config()
    data["system_health"] = status
    data.pop("system_health_state", None)
    save_config(data)


def set_system_health_state(status: str, note: str) -> None:
    """Persist the structured system health state."""

    normalised_status = str(status or "").strip().lower()
    if normalised_status not in SYSTEM_HEALTH_STATUSES:
        normalised_status = "online"

    note_value = ""
    if note is not None:
        note_value = " ".join(str(note).splitlines()).strip()
    if len(note_value) > _SYSTEM_HEALTH_NOTE_LIMIT:
        note_value = note_value[:_SYSTEM_HEALTH_NOTE_LIMIT].rstrip()

    payload = {"status": normalised_status, "note": note_value}

    data = load_config()
    data["system_health_state"] = payload
    data["system_health"] = _format_system_health_summary(normalised_status, note_value)
    save_config(data)

