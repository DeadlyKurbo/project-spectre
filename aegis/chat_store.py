"""Local chat message store for A.E.G.I.S.

Messages are stored in a JSON file in the user's application data directory.
File permissions are restricted to the current user for security.
"""

from __future__ import annotations

import json
import os
import platform
import stat
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _data_dir() -> Path:
    """Return the AEGIS application data directory (user-specific, secure)."""
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    path = Path(base) / "AEGIS"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _chat_file() -> Path:
    """Path to the chat messages JSON file."""
    return _data_dir() / "chat_messages.json"


def _secure_file(path: Path) -> None:
    """Restrict file permissions to current user only (Unix/macOS)."""
    if platform.system() in ("Darwin", "Linux"):
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


def load_messages() -> list[dict[str, Any]]:
    """Load all messages from local storage."""
    path = _chat_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        messages = data.get("messages", [])
        return messages if isinstance(messages, list) else []
    except (json.JSONDecodeError, OSError):
        return []


_MAX_MESSAGES = 500


def save_message(operator_name: str, message: str) -> dict[str, Any]:
    """Append a message and persist. Returns the saved message dict."""
    messages = load_messages()
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "id": str(uuid.uuid4()),
        "operator_handle": operator_name,
        "operator": operator_name,
        "message": message,
        "created_at": now,
    }
    messages.append(entry)
    # Prune old messages to keep storage bounded
    if len(messages) > _MAX_MESSAGES:
        messages = messages[-_MAX_MESSAGES:]

    path = _chat_file()
    payload = {"messages": messages, "updated_at": now}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _secure_file(path)
    return entry


def clear_messages() -> None:
    """Clear all stored messages (for testing or cleanup)."""
    path = _chat_file()
    if path.exists():
        path.write_text(json.dumps({"messages": [], "updated_at": ""}), encoding="utf-8")
        _secure_file(path)
