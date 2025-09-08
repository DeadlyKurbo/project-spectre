"""Helpers for persisting lightweight configuration.

Configuration values such as the log channel, build version and status message
ID need to persist across bot restarts and, ideally, across deployments.  The
original implementation wrote these settings to a JSON file on the local
filesystem.  That approach works for a single instance but does not propagate to
other nodes and is lost if the container is rebuilt.

To make the configuration truly persistent the data is now stored via the
``storage_spaces`` helpers which point at DigitalOcean Spaces (or fall back to
the local ``dossiers`` directory during tests).  The storage path is governed by
``CONFIG_FILE`` which defaults to ``config/config.json`` relative to the root of
the dossier storage.  If ``CONFIG_FILE`` is set to an absolute path the module
will read and write that local file instead – this behaviour preserves the
ability for tests to override the location with a temporary directory.

All helpers return sensible defaults when the configuration file does not exist
or contains invalid JSON.
"""

import json
import os

from storage_spaces import read_json, save_json

# Default path within the dossier storage.  Tests may monkeypatch this to an
# absolute path which forces local file access instead.
CONFIG_FILE = "config/config.json"


def load_config():
    """Return the persisted configuration dictionary.

    When ``CONFIG_FILE`` is an absolute path the function interacts with the
    local filesystem for backwards compatibility with existing tests.  For
    relative paths the file is retrieved via ``storage_spaces`` which stores the
    data in DigitalOcean Spaces (or a local fallback directory when credentials
    are not configured).
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

    # Relative path -> storage spaces
    try:
        return read_json(CONFIG_FILE)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def save_config(data):
    """Persist ``data`` to ``CONFIG_FILE``.

    Uses ``storage_spaces`` for relative paths so the configuration is saved in
    the same DigitalOcean Space as the dossiers.  When ``CONFIG_FILE`` is
    absolute the data is written to the local filesystem instead.  The JSON is
    formatted with ``indent=2`` for easier manual inspection.
    """

    if os.path.isabs(CONFIG_FILE):
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    else:
        save_json(CONFIG_FILE, data)

def get_log_channel():
    """Return the configured log channel ID if available.

    The value is normalised to an ``int`` so callers receive a consistent
    type even if the JSON file was edited manually and stored the ID as a
    string.
    """
    channel_id = load_config().get("log_channel_id")
    if channel_id is None:
        return None
    try:
        return int(channel_id)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None

def set_log_channel(channel_id: int):
    """Persist ``channel_id`` as the log channel.

    ``channel_id`` is cast to ``int`` before saving so that manual edits or
    accidental passing of a string cannot corrupt the configuration file.
    """
    data = load_config()
    data["log_channel_id"] = int(channel_id)
    save_config(data)



def get_report_channel() -> int | None:
    """Return the configured moderator report channel ID if available."""

    channel_id = load_config().get("report_channel_id")
    if channel_id is None:
        return None
    try:
        return int(channel_id)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def set_report_channel(channel_id: int) -> None:
    """Persist ``channel_id`` as the moderator report channel."""

    data = load_config()
    data["report_channel_id"] = int(channel_id)
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

def get_status_message_id():
    """Return the stored status message ID if available."""
    msg_id = load_config().get("status_message_id")
    if msg_id is None:
        return None
    try:
        return int(msg_id)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def set_status_message_id(message_id: int) -> None:
    """Persist ``message_id`` for the status message."""
    data = load_config()
    data["status_message_id"] = int(message_id)
    save_config(data)
