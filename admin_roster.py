"""Helpers for storing and retrieving admin profile bios."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re

from storage_spaces import read_json, write_json

ADMIN_BIOS_KEY = "owner/admin-bios.json"
_MAX_BIO_LENGTH = 800


@dataclass(slots=True)
class AdminBio:
    """Represents the stored bio text for a single admin."""

    user_id: str
    bio: str
    updated_at: str | None = None

    def to_payload(self) -> dict[str, str]:
        payload: dict[str, str] = {"bio": self.bio}
        if self.updated_at:
            payload["updated_at"] = self.updated_at
        return payload


def _normalise_user_id(value: str | int | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned or not cleaned.isdigit():
        return None
    return cleaned


def _normalise_bio_text(text: str | None) -> str:
    if text is None:
        return ""
    cleaned = str(text).replace("\r\n", "\n").replace("\r", "\n")
    # Bios should store plain text. If earlier versions stored HTML <br> tags,
    # convert them back into newlines so editors don't see the markup.
    cleaned = re.sub(r"(?i)<br\s*/?>", "\n", cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) > _MAX_BIO_LENGTH:
        cleaned = cleaned[:_MAX_BIO_LENGTH].rstrip()
    return cleaned


def load_admin_bios() -> dict[str, AdminBio]:
    """Load stored bios keyed by Discord user ID."""

    try:
        raw = read_json(ADMIN_BIOS_KEY) or {}
    except FileNotFoundError:
        # Fresh installs won't have a bios document yet.  Treat that the same as
        # an empty payload instead of surfacing a 500 error when the admin team
        # page is opened for the first time.
        return {}
    if not isinstance(raw, dict):
        return {}

    bios: dict[str, AdminBio] = {}
    for key, value in raw.items():
        user_id = _normalise_user_id(key)
        if not user_id:
            continue
        bio_text = ""
        updated_at = None
        if isinstance(value, dict):
            bio_text = _normalise_bio_text(value.get("bio"))
            ts = value.get("updated_at")
            if isinstance(ts, str):
                updated_at = ts.strip() or None
        else:
            bio_text = _normalise_bio_text(str(value))
        if not bio_text and not updated_at:
            continue
        bios[user_id] = AdminBio(user_id=user_id, bio=bio_text, updated_at=updated_at)
    return bios


def save_admin_bio(user_id: str | int, bio: str | None) -> dict[str, AdminBio]:
    """Persist ``bio`` for ``user_id`` and return the refreshed mapping."""

    normalized_id = _normalise_user_id(user_id)
    if not normalized_id:
        raise ValueError("A numeric Discord user ID is required")

    bios = load_admin_bios()
    cleaned = _normalise_bio_text(bio)
    if not cleaned:
        if normalized_id in bios:
            bios.pop(normalized_id, None)
        write_json(ADMIN_BIOS_KEY, {uid: entry.to_payload() for uid, entry in bios.items()})
        return bios

    entry = AdminBio(
        user_id=normalized_id,
        bio=cleaned,
        updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    bios[normalized_id] = entry
    write_json(ADMIN_BIOS_KEY, {uid: bio_entry.to_payload() for uid, bio_entry in bios.items()})
    return bios
