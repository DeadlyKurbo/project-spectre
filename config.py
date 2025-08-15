"""Helpers for persisting lightweight configuration.

Currently the bot only stores the ID of the channel used for logging
administrative actions.  The previous implementation wrote this data to a
``config.json`` file, which clashed with an earlier version of the project that
expected the data in ``log_channel.json``.  As a result the bot would happily
save the value to ``config.json`` but would attempt to load it from the old file
on start-up, leaving ``LOG_CHANNEL_ID`` unset every time the process restarted.

To keep backwards compatibility and ensure the value actually persists we store
the configuration in ``log_channel.json`` again.  The helper functions below
automatically fall back to an empty dictionary if the file does not yet exist
and write pretty formatted JSON when saving so that manual editing remains
straight‑forward.
"""

import json
import os

BASE_DIR = os.path.dirname(__file__)
DATA_ROOT = os.getenv("DATA_ROOT")
if DATA_ROOT:
    CONFIG_FILE = os.path.join(DATA_ROOT, "log_channel.json")
else:
    # Persist the log channel in ``log_channel.json`` so it matches the ignored
    # file name used by the repository and older deployments.
    CONFIG_FILE = os.path.join(BASE_DIR, "log_channel.json")

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_config(data):
    """Persist ``data`` to ``CONFIG_FILE``.

    Using ``indent=2`` makes the file human readable which is handy for
    debugging or manual edits.
    """
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

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
