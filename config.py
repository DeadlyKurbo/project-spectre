"""Drive-backed config + local mirror."""

import json
import os

BASE_DIR = os.path.dirname(__file__)
CONFIG_FILE = os.path.join(BASE_DIR, "log_channel.json")

# lazy import to avoid circular at module import time
def _drive():
    from drive_storage import get_drive_config, save_drive_config  # type: ignore
    return get_drive_config, save_drive_config

def load_local():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_local(data: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_log_channel():
    """Prefer Drive config; fall back to local; normalize to int."""
    try:
        get_drive_config, _ = _drive()
        data = get_drive_config() or {}
        cid = data.get("log_channel_id")
        if cid is not None:
            try:
                return int(cid)
            except (TypeError, ValueError):
                pass
    except Exception:
        pass
    # fallback local
    cid = load_local().get("log_channel_id")
    try:
        return int(cid) if cid is not None else None
    except (TypeError, ValueError):
        return None

def set_log_channel(channel_id: int):
    """Write to Drive AND local mirror."""
    payload = {"log_channel_id": int(channel_id)}
    try:
        _, save_drive_config = _drive()
        save_drive_config(payload)
    except Exception:
        # still mirror locally even if Drive save fails
        pass
    save_local(payload)
