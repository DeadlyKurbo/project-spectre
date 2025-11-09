"""Helpers for managing cross-instance archive link codes.

Each Spectre deployment receives a persistent share code which is stored in
DigitalOcean Spaces (or the local filesystem when running in development
mode).  Guild configurations register their archive metadata with the code so
other deployments can discover and link to the same storage root when provided
with the share code by an operator.

The module keeps the storage interactions intentionally simple – small JSON
documents are written for the instance descriptor as well as for the code
index.  This avoids introducing a new database dependency while making it
straightforward to inspect or back up the state manually when required.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import secrets
from typing import Iterable

from storage_spaces import read_json, write_json

_INSTANCE_STATE_PATH = "link-registry/instance.json"
_INSTANCE_INDEX_PREFIX = "link-registry/instances"
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@dataclass(slots=True)
class ArchiveSummary:
    """Minimal metadata exposed for a linked archive."""

    guild_id: str
    root_prefix: str
    name: str | None
    updated_at: str

    def to_payload(self) -> dict[str, str | None]:
        payload: dict[str, str | None] = {
            "guild_id": self.guild_id,
            "root_prefix": self.root_prefix,
            "updated_at": self.updated_at,
        }
        if self.name:
            payload["name"] = self.name
        return payload


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _instance_index_path(code: str) -> str:
    return f"{_INSTANCE_INDEX_PREFIX}/{code}.json"


def _clean_code(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().upper().replace(" ", "")
    if not cleaned:
        return None
    # Allow hyphen-separated segments but remove stray characters.
    parts = [segment for segment in cleaned.split("-") if segment]
    candidate = "-".join(parts) if parts else cleaned
    for ch in candidate:
        if ch not in _CODE_ALPHABET and ch != "-":
            return None
    return candidate


def _generate_code(length: int = 12) -> str:
    segments = []
    for _ in range(max(1, length // 4)):
        part = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
        segments.append(part)
    return "-".join(segments)


def _load_instance_state() -> dict:
    try:
        data = read_json(_INSTANCE_STATE_PATH)
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _write_instance_state(payload: dict) -> None:
    write_json(_INSTANCE_STATE_PATH, payload)


def get_instance_code() -> str:
    """Return the persistent share code for this deployment."""

    state = _load_instance_state()
    stored = _clean_code(state.get("code") if isinstance(state, dict) else None)
    if stored:
        existing = _load_instance_index(stored)
        if not existing:
            now = _now_iso()
            write_json(_instance_index_path(stored), {"code": stored, "archives": {}, "updated_at": now})
        return stored

    code = _generate_code()
    now = _now_iso()
    payload = {
        "code": code,
        "created_at": now,
        "updated_at": now,
    }
    _write_instance_state(payload)
    # Initialise the index document so subsequent lookups succeed even before
    # archives register themselves.
    write_json(_instance_index_path(code), {"code": code, "archives": {}, "updated_at": now})
    return code


def _load_instance_index(code: str) -> dict:
    try:
        doc = read_json(_instance_index_path(code))
    except FileNotFoundError:
        return {}
    if not isinstance(doc, dict):
        return {}
    archives = doc.get("archives")
    if not isinstance(archives, dict):
        doc["archives"] = {}
    return doc


def _write_instance_index(code: str, payload: dict) -> None:
    write_json(_instance_index_path(code), payload)


def _summaries_from_payload(payload: dict) -> list[ArchiveSummary]:
    archives = payload.get("archives")
    if not isinstance(archives, dict):
        return []
    result: list[ArchiveSummary] = []
    for raw in archives.values():
        if not isinstance(raw, dict):
            continue
        guild_id = str(raw.get("guild_id") or "").strip()
        root_prefix = str(raw.get("root_prefix") or "").strip()
        if not guild_id or not root_prefix:
            continue
        name = str(raw.get("name") or "").strip() or None
        updated_at = str(raw.get("updated_at") or "").strip()
        if not updated_at:
            updated_at = _now_iso()
        result.append(
            ArchiveSummary(
                guild_id=guild_id,
                root_prefix=root_prefix,
                name=name,
                updated_at=updated_at,
            )
        )
    # Preserve deterministic order for API consumers.
    result.sort(key=lambda summary: summary.guild_id)
    return result


def get_instance_summary() -> dict[str, object]:
    """Return metadata about this instance and its registered archives."""

    code = get_instance_code()
    payload = _load_instance_index(code)
    payload.setdefault("code", code)
    payload.setdefault("updated_at", _now_iso())
    summaries = _summaries_from_payload(payload)
    return {
        "code": code,
        "updated_at": payload.get("updated_at"),
        "archives": [summary.to_payload() for summary in summaries],
    }


def register_archive(
    guild_id: int,
    *,
    root_prefix: str,
    name: str | None = None,
) -> None:
    """Register or update ``guild_id`` metadata for the instance share code."""

    code = get_instance_code()
    payload = _load_instance_index(code)
    archives = payload.setdefault("archives", {})
    now = _now_iso()
    guild_key = str(guild_id)
    entry = {
        "guild_id": guild_key,
        "root_prefix": root_prefix.strip().strip("/"),
        "updated_at": now,
    }
    if name:
        entry["name"] = name.strip()
    archives[guild_key] = entry
    payload["code"] = code
    payload["updated_at"] = now
    _write_instance_index(code, payload)


def unregister_archive(guild_id: int) -> None:
    """Remove ``guild_id`` from the local share code registry."""

    code = get_instance_code()
    payload = _load_instance_index(code)
    archives = payload.get("archives")
    if isinstance(archives, dict) and str(guild_id) in archives:
        archives.pop(str(guild_id), None)
        payload["updated_at"] = _now_iso()
        _write_instance_index(code, payload)


def resolve_code(code: str) -> dict[str, object]:
    """Return the archive listing for ``code``.

    Raises
    ------
    FileNotFoundError
        If the provided code does not exist in storage.
    ValueError
        If the code is malformed.
    """

    cleaned = _clean_code(code)
    if not cleaned:
        raise ValueError("Invalid archive code")

    payload = _load_instance_index(cleaned)
    if not payload:
        raise FileNotFoundError(cleaned)

    payload.setdefault("code", cleaned)
    payload.setdefault("updated_at", _now_iso())
    summaries = _summaries_from_payload(payload)
    return {
        "code": cleaned,
        "updated_at": payload.get("updated_at"),
        "archives": [summary.to_payload() for summary in summaries],
    }


def import_links(code: str, entries: Iterable[dict[str, str | None]]) -> list[dict[str, str | None]]:
    """Normalise link entries coming from external instances.

    The helper ensures each returned entry includes the originating code so the
    caller can persist it in guild configuration documents.
    """

    cleaned = _clean_code(code)
    if not cleaned:
        raise ValueError("Invalid archive code")

    normalised: list[dict[str, str | None]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        root_prefix = str(entry.get("root_prefix") or "").strip().strip("/")
        if not root_prefix:
            continue
        guild_id = str(entry.get("guild_id") or "").strip()
        name = str(entry.get("name") or "").strip() or None
        payload = {"code": cleaned, "root_prefix": root_prefix}
        if guild_id:
            payload["guild_id"] = guild_id
        if name:
            payload["name"] = name
        normalised.append(payload)
    return normalised

