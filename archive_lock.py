"""Archive lockdown state shared by the Discord bot and the website.

High Command engages a lockdown from the archivist console; while it is on,
only High Command may open the archive. The bot and the website run as
separate processes, so the flag is kept in storage: the website enforces the
same lockdown, and a bot restart no longer lifts it silently.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import storage_spaces

logger = logging.getLogger(__name__)

# The website re-reads the flag at most this often per guild.
READ_TTL_SECONDS = 10.0

_read_cache: dict[int, tuple[float, bool]] = {}


def _lock_key(guild_id: int) -> str:
    return f"archive-locks/{int(guild_id)}.json"


def read_lock(guild_id: int) -> bool:
    """Return the stored lockdown flag for ``guild_id`` (False when never set)."""

    try:
        data = storage_spaces.read_json(_lock_key(guild_id))
    except FileNotFoundError:
        return False
    return bool(data.get("locked")) if isinstance(data, dict) else False


def write_lock(guild_id: int, locked: bool, *, actor: str | None = None) -> None:
    storage_spaces.save_json(
        _lock_key(guild_id),
        {
            "locked": bool(locked),
            "actor": actor or "",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    _read_cache.pop(int(guild_id), None)


def is_locked(guild_id: int) -> bool:
    """Cached read for the website; storage errors fail closed (locked)."""

    gid = int(guild_id)
    cached = _read_cache.get(gid)
    if cached and time.monotonic() - cached[0] < READ_TTL_SECONDS:
        return cached[1]
    try:
        locked = read_lock(gid)
    except Exception:
        logger.exception("Failed to read archive lockdown state for guild %s", gid)
        return True
    _read_cache[gid] = (time.monotonic(), locked)
    return locked
