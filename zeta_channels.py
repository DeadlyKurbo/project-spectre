"""Project ZETA channels: the built-in #zeta-ops plus channels command creates.

The registry, ``zeta/channels.json``, lists the extra channels in the order
they were made. Each extra channel keeps its messages in
``zeta/channels/<id>.json`` and its pictures and videos in
``zeta/media/<id>/``, and like #zeta-ops it purges messages after 24 hours.
#zeta-ops itself still lives in its original log, ``alice/chat-log.json``.

Every function takes the storage backend (``storage_spaces``) as its first
argument and writes with ETag checks, retrying a few times when another
request got there first.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

DEFAULT_CHANNEL = "zeta-ops"
DEFAULT_TOPIC = "Channel · purged after 24 hours · nothing is logged"
REGISTRY_KEY = "zeta/channels.json"
MAX_CHANNELS = 20
MAX_NAME_LENGTH = 32
MAX_TOPIC_LENGTH = 120
_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_WRITE_ATTEMPTS = 3


class ChannelConflict(RuntimeError):
    """The registry kept changing while saving; the caller should retry."""


def clean_id(value: Any) -> str:
    """``"Field Ops!"`` becomes ``"field-ops"``; accents are folded, other characters dropped."""

    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:MAX_NAME_LENGTH].strip("-")


def clean_topic(value: Any) -> str:
    text = "".join(char for char in str(value or "") if char.isprintable())
    return " ".join(text.split())[:MAX_TOPIC_LENGTH]


def is_channel_id(value: Any) -> bool:
    text = str(value or "")
    return len(text) <= MAX_NAME_LENGTH and bool(_ID_RE.fullmatch(text))


def log_key(channel_id: str, default_key: str) -> str:
    return default_key if channel_id == DEFAULT_CHANNEL else f"zeta/channels/{channel_id}.json"


def media_folder(channel_id: str) -> str:
    return f"zeta/media/{channel_id}"


def _read(backend) -> tuple[list[dict[str, str]], str | None]:
    try:
        payload, etag = backend.read_json(REGISTRY_KEY, with_etag=True)
    except FileNotFoundError:
        return [], None
    return _clean(payload), etag


def _clean(payload: Any) -> list[dict[str, str]]:
    raw = payload.get("channels") if isinstance(payload, dict) else None
    channels: list[dict[str, str]] = []
    seen = {DEFAULT_CHANNEL}
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        channel_id = str(entry.get("id") or "")
        if not is_channel_id(channel_id) or channel_id in seen:
            continue
        seen.add(channel_id)
        channels.append(
            {
                "id": channel_id,
                "topic": clean_topic(entry.get("topic")),
                "created_by": str(entry.get("created_by") or ""),
                "created_at": str(entry.get("created_at") or ""),
            }
        )
    return channels[: MAX_CHANNELS - 1]


def list_channels(backend) -> list[dict[str, str]]:
    """Every channel, #zeta-ops first."""

    channels, _etag = _read(backend)
    default = {"id": DEFAULT_CHANNEL, "topic": DEFAULT_TOPIC, "created_by": "", "created_at": ""}
    return [default, *channels]


def find(backend, channel_id: str) -> dict[str, str] | None:
    return next((c for c in list_channels(backend) if c["id"] == channel_id), None)


def create(backend, *, name: Any, topic: Any, created_by: str, now: datetime | None = None) -> dict[str, str]:
    """Add a channel; raise ``ValueError`` with a reason the caller can show."""

    channel_id = clean_id(name)
    if not channel_id:
        raise ValueError("Give the channel a name with letters or numbers.")
    entry = {
        "id": channel_id,
        "topic": clean_topic(topic),
        "created_by": created_by,
        "created_at": (now or datetime.now(timezone.utc)).isoformat(),
    }
    for _attempt in range(_WRITE_ATTEMPTS):
        channels, etag = _read(backend)
        if channel_id == DEFAULT_CHANNEL or any(c["id"] == channel_id for c in channels):
            raise ValueError(f"#{channel_id} already exists.")
        if len(channels) + 1 >= MAX_CHANNELS:
            raise ValueError(f"Project ZETA can have at most {MAX_CHANNELS} channels.")
        if backend.write_json(REGISTRY_KEY, {"channels": [*channels, entry]}, etag=etag):
            return entry
    raise ChannelConflict("Channels changed while saving, please retry")


def remove(backend, channel_id: str) -> bool:
    """Drop a channel from the registry; ``False`` when it was not there."""

    for _attempt in range(_WRITE_ATTEMPTS):
        channels, etag = _read(backend)
        kept = [c for c in channels if c["id"] != channel_id]
        if len(kept) == len(channels):
            return False
        if backend.write_json(REGISTRY_KEY, {"channels": kept}, etag=etag):
            return True
    raise ChannelConflict("Channels changed while saving, please retry")


__all__ = [
    "ChannelConflict",
    "DEFAULT_CHANNEL",
    "DEFAULT_TOPIC",
    "MAX_CHANNELS",
    "MAX_NAME_LENGTH",
    "MAX_TOPIC_LENGTH",
    "clean_id",
    "create",
    "find",
    "is_channel_id",
    "list_channels",
    "log_key",
    "media_folder",
    "remove",
]
