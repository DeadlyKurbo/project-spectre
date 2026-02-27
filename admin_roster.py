"""Helpers for storing and retrieving admin team profile data."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import html
import re

from storage_spaces import read_json, write_json

ADMIN_BIOS_KEY = "owner/admin-bios.json"
ADMIN_TEAM_SETTINGS_KEY = "owner/admin-team-settings.json"
_MAX_BIO_LENGTH = 800
_MAX_RANK_LENGTH = 80


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


@dataclass(slots=True)
class AdminTeamSettings:
    """Persisted controls for who appears on the admin team page."""

    members: list[str]
    ranks: dict[str, str]

    def to_payload(self) -> dict[str, object]:
        return {
            "members": list(self.members),
            "ranks": dict(self.ranks),
        }


def _normalise_user_id(value: str | int | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned or not cleaned.isdigit():
        return None
    return cleaned


def normalise_bio_text(text: str | None) -> str:
    if text is None:
        return ""
    cleaned = html.unescape(str(text))
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    # Bios should store plain text. If earlier versions stored HTML <br> tags,
    # convert them back into newlines so editors don't see the markup.
    cleaned = re.sub(r"(?i)<br\s*/?>", "\n", cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) > _MAX_BIO_LENGTH:
        cleaned = cleaned[:_MAX_BIO_LENGTH].rstrip()
    return cleaned


def normalise_rank_text(text: str | None) -> str:
    if text is None:
        return ""
    cleaned = html.unescape(str(text))
    cleaned = cleaned.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > _MAX_RANK_LENGTH:
        cleaned = cleaned[:_MAX_RANK_LENGTH].rstrip()
    return cleaned


def load_admin_team_settings() -> AdminTeamSettings:
    """Load custom admin team members and manual ranks."""

    try:
        raw = read_json(ADMIN_TEAM_SETTINGS_KEY) or {}
    except FileNotFoundError:
        return AdminTeamSettings(members=[], ranks={})

    if not isinstance(raw, dict):
        return AdminTeamSettings(members=[], ranks={})

    members_raw = raw.get("members")
    members: list[str] = []
    if isinstance(members_raw, list):
        seen: set[str] = set()
        for candidate in members_raw:
            user_id = _normalise_user_id(candidate)
            if not user_id or user_id in seen:
                continue
            seen.add(user_id)
            members.append(user_id)

    ranks_raw = raw.get("ranks")
    ranks: dict[str, str] = {}
    if isinstance(ranks_raw, dict):
        for candidate, value in ranks_raw.items():
            user_id = _normalise_user_id(candidate)
            if not user_id:
                continue
            rank_text = normalise_rank_text(str(value) if value is not None else "")
            if rank_text:
                ranks[user_id] = rank_text

    return AdminTeamSettings(members=members, ranks=ranks)


def save_admin_team_settings(settings: AdminTeamSettings) -> AdminTeamSettings:
    """Persist the supplied team settings after cleaning IDs and rank strings."""

    seen: set[str] = set()
    cleaned_members: list[str] = []
    for candidate in settings.members:
        user_id = _normalise_user_id(candidate)
        if not user_id or user_id in seen:
            continue
        seen.add(user_id)
        cleaned_members.append(user_id)

    cleaned_ranks: dict[str, str] = {}
    for candidate, rank in settings.ranks.items():
        user_id = _normalise_user_id(candidate)
        if not user_id:
            continue
        rank_text = normalise_rank_text(rank)
        if rank_text:
            cleaned_ranks[user_id] = rank_text

    cleaned = AdminTeamSettings(members=cleaned_members, ranks=cleaned_ranks)
    write_json(ADMIN_TEAM_SETTINGS_KEY, cleaned.to_payload())
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
            bio_text = normalise_bio_text(value.get("bio"))
            ts = value.get("updated_at")
            if isinstance(ts, str):
                updated_at = ts.strip() or None
        else:
            bio_text = normalise_bio_text(str(value))
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
    cleaned = normalise_bio_text(bio)
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
