"""Discord servers the admin console has banned from using the bot.

Like ``bot_control``, the website and the bot share this through one document
in the persistent store, ``system/guild_blacklist.json``. The website writes
it; the bot re-reads it every few seconds and stays in a blacklisted server
but answers everything there with a notice that the server is blacklisted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from persistent_store import read_json, save_json

GUILD_BLACKLIST_KEY = "system/guild_blacklist.json"
# How often the bot re-reads the list, so how long a ban or lift takes to apply.
GUILD_BLACKLIST_POLL_SECONDS = 10
GUILD_BLACKLIST_REASON_MAX_LENGTH = 500
GUILD_NAME_MAX_LENGTH = 100


def _clean_text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())[:limit].rstrip()
    return cleaned or None


def normalise_guild_id(value: Any) -> str | None:
    """Return ``value`` as a Discord server ID string, or ``None`` if it is not one."""

    cleaned = str(value or "").strip()
    # Snowflakes are 17-20 digits today; allow a little room either side.
    if not cleaned.isdigit() or not 15 <= len(cleaned) <= 25:
        return None
    return cleaned


def _read_entries() -> dict[str, dict[str, Any]]:
    try:
        raw = read_json(GUILD_BLACKLIST_KEY)
    except FileNotFoundError:
        return {}
    guilds = raw.get("guilds") if isinstance(raw, dict) else None
    if not isinstance(guilds, dict):
        return {}
    return {
        guild_id: entry
        for guild_id, entry in guilds.items()
        if normalise_guild_id(guild_id) == guild_id and isinstance(entry, dict)
    }


def _save_entries(entries: dict[str, dict[str, Any]]) -> None:
    save_json(
        GUILD_BLACKLIST_KEY,
        {
            "guilds": entries,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )


def list_blacklisted_guilds() -> list[dict[str, Any]]:
    """Return every blacklisted server, most recently banned first. Storage errors propagate."""

    entries = [
        {
            "guild_id": guild_id,
            "name": _clean_text(entry.get("name"), GUILD_NAME_MAX_LENGTH),
            "reason": _clean_text(entry.get("reason"), GUILD_BLACKLIST_REASON_MAX_LENGTH),
            "actor": _clean_text(entry.get("actor"), 200),
            "banned_at": _clean_text(entry.get("banned_at"), 40),
        }
        for guild_id, entry in _read_entries().items()
    ]
    entries.sort(key=lambda entry: entry["banned_at"] or "", reverse=True)
    return entries


def blacklisted_guild_ids() -> set[int]:
    """Return the blacklisted server IDs. Storage errors propagate."""

    return {int(guild_id) for guild_id in _read_entries()}


# The bot process keeps the last list it read here, so the checks on its hot
# paths (every interaction, every menu deploy) never wait on storage.
_bot_blacklist: frozenset[int] = frozenset()


def refresh_bot_blacklist() -> frozenset[int]:
    """Re-read the list into the bot's copy. Storage errors propagate and keep the old copy."""

    global _bot_blacklist
    _bot_blacklist = frozenset(blacklisted_guild_ids())
    return _bot_blacklist


def is_guild_blacklisted(guild_id: Any) -> bool:
    """Return whether the bot's last read of the list includes ``guild_id``."""

    try:
        return int(guild_id) in _bot_blacklist
    except (TypeError, ValueError):
        return False


def blacklist_guild(
    guild_id: Any,
    *,
    reason: str | None,
    actor: str | None,
    name: str | None = None,
) -> dict[str, Any]:
    """Add a server to the blacklist, replacing its entry if it is already on it."""

    cleaned_id = normalise_guild_id(guild_id)
    if cleaned_id is None:
        raise ValueError("Enter a valid Discord server ID.")
    cleaned_reason = _clean_text(reason, GUILD_BLACKLIST_REASON_MAX_LENGTH)
    if cleaned_reason is None:
        raise ValueError("Give a reason for blacklisting the server.")

    entries = _read_entries()
    entry = {
        # Keep the name from the first ban once the bot is no longer in the server.
        "name": _clean_text(name, GUILD_NAME_MAX_LENGTH) or entries.get(cleaned_id, {}).get("name"),
        "reason": cleaned_reason,
        "actor": _clean_text(actor, 200),
        "banned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    entries[cleaned_id] = entry
    _save_entries(entries)
    return {"guild_id": cleaned_id, **entry}


def unblacklist_guild(guild_id: Any) -> bool:
    """Remove a server from the blacklist. Returns ``False`` if it was not on it."""

    cleaned_id = normalise_guild_id(guild_id)
    entries = _read_entries()
    if cleaned_id is None or cleaned_id not in entries:
        return False
    del entries[cleaned_id]
    _save_entries(entries)
    return True


__all__ = [
    "GUILD_BLACKLIST_KEY",
    "GUILD_BLACKLIST_POLL_SECONDS",
    "GUILD_BLACKLIST_REASON_MAX_LENGTH",
    "blacklist_guild",
    "blacklisted_guild_ids",
    "is_guild_blacklisted",
    "list_blacklisted_guilds",
    "normalise_guild_id",
    "refresh_bot_blacklist",
    "unblacklist_guild",
]
