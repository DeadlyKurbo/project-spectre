"""Project ZETA profiles: the name and picture a member chose for themselves.

``zeta/profiles.json`` maps a member ID (Discord or guest) to an optional
custom ``name`` and an optional ``avatar``, the file name of their picture in
``zeta/avatars/``. A member without a profile shows up as before: Discord
members under their masked ``Operator X`` callsign, guests under the name
they joined with. Checking that a custom name is free is the caller's job.

Every function takes the storage backend (``storage_spaces``) as its first
argument and writes with ETag checks, retrying a few times when another
request got there first.
"""

from __future__ import annotations

from typing import Any, Callable

import zeta_media

PROFILES_KEY = "zeta/profiles.json"
AVATAR_FOLDER = "zeta/avatars"
_WRITE_ATTEMPTS = 3


class ProfileConflict(RuntimeError):
    """The profiles kept changing while saving; the caller should retry."""


def _clean(payload: Any) -> dict[str, dict[str, str]]:
    raw = payload.get("profiles") if isinstance(payload, dict) else None
    profiles: dict[str, dict[str, str]] = {}
    for member_id, entry in (raw or {}).items():
        if not isinstance(entry, dict):
            continue
        profile = {}
        name = str(entry.get("name") or "").strip()
        if name:
            profile["name"] = name
        if zeta_media.is_media_file(entry.get("avatar")):
            profile["avatar"] = entry["avatar"]
        if profile:
            profiles[str(member_id)] = profile
    return profiles


def load(backend) -> dict[str, dict[str, str]]:
    try:
        payload = backend.read_json(PROFILES_KEY)
    except FileNotFoundError:
        return {}
    return _clean(payload)


def _update(backend, member_id: str, change: Callable[[dict[str, str]], None]) -> dict[str, str]:
    """Apply ``change`` to the member's profile; return the profile as it was before."""

    for _attempt in range(_WRITE_ATTEMPTS):
        try:
            payload, etag = backend.read_json(PROFILES_KEY, with_etag=True)
        except FileNotFoundError:
            payload, etag = None, None
        profiles = _clean(payload)
        before = dict(profiles.get(member_id) or {})
        after = dict(before)
        change(after)
        if after == before:
            return before
        if after:
            profiles[member_id] = after
        else:
            profiles.pop(member_id, None)
        if backend.write_json(PROFILES_KEY, {"profiles": profiles}, etag=etag):
            return before
    raise ProfileConflict("Profiles changed while saving, please retry")


def set_name(backend, member_id: str, name: str | None) -> None:
    """Set the member's custom name, or clear it with ``None``."""

    def _change(profile):
        if name:
            profile["name"] = name
        else:
            profile.pop("name", None)

    _update(backend, member_id, _change)


def set_avatar(backend, member_id: str, fileobj=None, *, filename: str = "") -> None:
    """Replace the member's picture with ``fileobj``, or remove it when ``None``.

    Raises ``zeta_media.UploadRejected`` when the file is not a picture.
    """

    new_file = None
    if fileobj is not None:
        new_file = zeta_media.store(backend, AVATAR_FOLDER, fileobj, filename=filename, images_only=True)["file"]

    def _change(profile):
        if new_file:
            profile["avatar"] = new_file
        else:
            profile.pop("avatar", None)

    try:
        before = _update(backend, member_id, _change)
    except ProfileConflict:
        zeta_media.delete(backend, AVATAR_FOLDER, new_file)
        raise
    if before.get("avatar") != new_file:
        zeta_media.delete(backend, AVATAR_FOLDER, before.get("avatar"))


__all__ = ["AVATAR_FOLDER", "ProfileConflict", "load", "set_avatar", "set_name"]
