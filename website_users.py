"""Discord accounts that have signed in to the website.

The admin console picks from these when it opens a case against a person.
The website records each account as it signs in, in one document in the
persistent store, ``system/website_users.json``.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from persistent_store import read_json, save_json

WEBSITE_USERS_KEY = "system/website_users.json"
# Past this, the accounts seen longest ago are dropped to keep the document small.
WEBSITE_USERS_LIMIT = 5000
_NAME_MAX_LENGTH = 100

# Recording is a read-modify-write of one document, so concurrent sign-ins
# in this process take turns.
_lock = threading.Lock()


def _clean_text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())[:limit].rstrip()
    return cleaned or None


def _clean_user_id(value: Any) -> str | None:
    cleaned = str(value or "").strip()
    if not cleaned.isdigit() or not 5 <= len(cleaned) <= 25:
        return None
    return cleaned


def _read_users() -> dict[str, dict[str, Any]]:
    try:
        raw = read_json(WEBSITE_USERS_KEY)
    except FileNotFoundError:
        return {}
    users = raw.get("users") if isinstance(raw, dict) else None
    if not isinstance(users, dict):
        return {}
    return {
        user_id: entry
        for user_id, entry in users.items()
        if _clean_user_id(user_id) == user_id and isinstance(entry, dict)
    }


def record_website_user(user: Any) -> dict[str, Any] | None:
    """Add or refresh a signed-in account from its Discord user object.

    Returns ``None`` when ``user`` has no valid Discord ID. Storage errors propagate.
    """

    user_id = _clean_user_id(user.get("id")) if isinstance(user, dict) else None
    if user_id is None:
        return None
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _lock:
        users = _read_users()
        previous = users.pop(user_id, {})
        entry = {
            "username": _clean_text(user.get("username"), _NAME_MAX_LENGTH),
            "global_name": _clean_text(user.get("global_name"), _NAME_MAX_LENGTH),
            "avatar": _clean_text(user.get("avatar"), 100),
            "first_seen_at": previous.get("first_seen_at") or now,
            "last_seen_at": now,
        }
        users[user_id] = entry
        if len(users) > WEBSITE_USERS_LIMIT:
            newest = sorted(users.items(), key=lambda item: str(item[1].get("last_seen_at") or ""), reverse=True)
            users = dict(newest[:WEBSITE_USERS_LIMIT])
        save_json(WEBSITE_USERS_KEY, {"users": users, "updated_at": now})
    return {"id": user_id, **entry}


def list_website_users() -> list[dict[str, Any]]:
    """Return every recorded account, most recently seen first. Storage errors propagate."""

    entries = [
        {
            "id": user_id,
            "username": _clean_text(entry.get("username"), _NAME_MAX_LENGTH),
            "global_name": _clean_text(entry.get("global_name"), _NAME_MAX_LENGTH),
            "avatar": _clean_text(entry.get("avatar"), 100),
            "first_seen_at": _clean_text(entry.get("first_seen_at"), 40),
            "last_seen_at": _clean_text(entry.get("last_seen_at"), 40),
        }
        for user_id, entry in _read_users().items()
    ]
    entries.sort(key=lambda entry: entry["last_seen_at"] or "", reverse=True)
    return entries


__all__ = [
    "WEBSITE_USERS_KEY",
    "WEBSITE_USERS_LIMIT",
    "list_website_users",
    "record_website_user",
]
