"""Project ZETA direct messages: private two-person threads that persist.

Unlike the ZETA channel, which purges itself after 24 hours, a direct message
stays until its author deletes it. Each thread lives in its own document,
``zeta/dm/threads/<a>_<b>.json``, readable only through the two participants'
sessions. Each member also has an inbox document,
``zeta/dm/inbox/<user>.json``, listing their threads with the latest message
time, a short preview and an unread count, so the thread list loads without
opening every thread. A third document, ``zeta/dm/pinged/<user>.json``,
remembers the newest message the site-wide ping already showed them.

Every function takes the storage backend (``storage_spaces``) as its first
argument and writes with ETag checks, retrying a few times when another
request got there first.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

DM_PREFIX = "zeta/dm"
MAX_MESSAGE_LENGTH = 600
MAX_MESSAGES_PER_THREAD = 2000
PREVIEW_LENGTH = 80
_WRITE_ATTEMPTS = 3


class DirectMessageConflict(RuntimeError):
    """Another request kept changing the same document; the caller should retry."""


class DirectMessageNotFound(LookupError):
    """The message does not exist or does not belong to the caller."""


def thread_id(user_a: str, user_b: str) -> str:
    return "_".join(sorted((user_a, user_b)))


def _thread_key(user_a: str, user_b: str) -> str:
    return f"{DM_PREFIX}/threads/{thread_id(user_a, user_b)}.json"


def _inbox_key(user_id: str) -> str:
    return f"{DM_PREFIX}/inbox/{user_id}.json"


def _pinged_key(user_id: str) -> str:
    return f"{DM_PREFIX}/pinged/{user_id}.json"


def _now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


def _read(backend, key: str) -> tuple[dict, str | None]:
    try:
        payload, etag = backend.read_json(key, with_etag=True)
    except FileNotFoundError:
        return {}, None
    return (payload if isinstance(payload, dict) else {}), etag


def _clean_messages(raw: Any) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("message") or "").strip()
        sender = str(entry.get("sender_id") or "").strip()
        if not text or not sender:
            continue
        messages.append(
            {
                "id": str(entry.get("id") or secrets.token_hex(8)),
                "sender_id": sender,
                "message": text[:MAX_MESSAGE_LENGTH],
                "created_at": str(entry.get("created_at") or _now_iso()),
            }
        )
    return messages[-MAX_MESSAGES_PER_THREAD:]


def _clean_inbox(raw: Any) -> dict[str, dict[str, Any]]:
    threads = raw.get("threads") if isinstance(raw, dict) else None
    cleaned: dict[str, dict[str, Any]] = {}
    for peer_id, entry in (threads or {}).items():
        if not isinstance(entry, dict):
            continue
        try:
            unread = max(0, int(entry.get("unread") or 0))
        except (TypeError, ValueError):
            unread = 0
        cleaned[str(peer_id)] = {
            "last_at": str(entry.get("last_at") or ""),
            "last_sender_id": str(entry.get("last_sender_id") or ""),
            "preview": str(entry.get("preview") or "")[:PREVIEW_LENGTH],
            "unread": unread,
        }
    return cleaned


def _preview(text: str) -> str:
    flat = " ".join(text.split())
    if len(flat) <= PREVIEW_LENGTH:
        return flat
    return flat[: PREVIEW_LENGTH - 1].rstrip() + "…"


def load_thread(backend, user_id: str, peer_id: str) -> list[dict[str, str]]:
    payload, _etag = _read(backend, _thread_key(user_id, peer_id))
    return _clean_messages(payload.get("messages"))


def load_inbox(backend, user_id: str) -> dict[str, dict[str, Any]]:
    payload, _etag = _read(backend, _inbox_key(user_id))
    return _clean_inbox(payload)


def _update_inbox(backend, owner_id: str, change) -> None:
    for _attempt in range(_WRITE_ATTEMPTS):
        payload, etag = _read(backend, _inbox_key(owner_id))
        threads = _clean_inbox(payload)
        if change(threads) is False:
            return
        if backend.write_json(_inbox_key(owner_id), {"threads": threads}, etag=etag):
            return
    raise DirectMessageConflict("Inbox changed while saving, please retry")


def _summarize(threads, peer_id: str, messages: list[dict[str, str]]) -> None:
    """Point the inbox entry for ``peer_id`` at the newest remaining message."""

    entry = threads.setdefault(peer_id, {"unread": 0})
    if messages:
        last = messages[-1]
        entry.update(
            last_at=last["created_at"],
            last_sender_id=last["sender_id"],
            preview=_preview(last["message"]),
        )
    else:
        entry.update(last_at="", last_sender_id="", preview="")


def append_message(
    backend,
    *,
    sender_id: str,
    recipient_id: str,
    message: str,
    now: datetime | None = None,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Add a message to the thread and both inboxes; return it and the thread."""

    text = message.strip()[:MAX_MESSAGE_LENGTH]
    if not text:
        raise ValueError("Message cannot be empty")

    entry = {
        "id": secrets.token_hex(8),
        "sender_id": sender_id,
        "message": text,
        "created_at": _now_iso(now),
    }
    key = _thread_key(sender_id, recipient_id)
    for _attempt in range(_WRITE_ATTEMPTS):
        payload, etag = _read(backend, key)
        messages = _clean_messages(payload.get("messages"))
        messages.append(entry)
        messages = messages[-MAX_MESSAGES_PER_THREAD:]
        document = {"participants": sorted((sender_id, recipient_id)), "messages": messages}
        if backend.write_json(key, document, etag=etag):
            break
    else:
        raise DirectMessageConflict("Conversation changed while sending, please retry")

    def _for_sender(threads):
        _summarize(threads, recipient_id, messages)

    def _for_recipient(threads):
        _summarize(threads, sender_id, messages)
        threads[sender_id]["unread"] = threads[sender_id].get("unread", 0) + 1

    _update_inbox(backend, sender_id, _for_sender)
    if recipient_id != sender_id:
        _update_inbox(backend, recipient_id, _for_recipient)
    return entry, messages


def delete_message(backend, *, user_id: str, peer_id: str, message_id: str) -> list[dict[str, str]]:
    """Delete one of ``user_id``'s own messages from the thread; return the thread."""

    key = _thread_key(user_id, peer_id)
    for _attempt in range(_WRITE_ATTEMPTS):
        payload, etag = _read(backend, key)
        messages = _clean_messages(payload.get("messages"))
        kept = [m for m in messages if not (m["id"] == message_id and m["sender_id"] == user_id)]
        if len(kept) == len(messages):
            raise DirectMessageNotFound("Message not found")
        document = {"participants": sorted((user_id, peer_id)), "messages": kept}
        if backend.write_json(key, document, etag=etag):
            break
    else:
        raise DirectMessageConflict("Conversation changed while deleting, please retry")

    _update_inbox(backend, user_id, lambda threads: _summarize(threads, peer_id, kept))

    def _for_peer(threads):
        if user_id not in threads:
            return False
        _summarize(threads, user_id, kept)

    _update_inbox(backend, peer_id, _for_peer)
    return kept


def mark_read(backend, *, user_id: str, peer_id: str) -> None:
    def _clear(threads):
        entry = threads.get(peer_id)
        if not entry or not entry.get("unread"):
            return False
        entry["unread"] = 0

    _update_inbox(backend, user_id, _clear)


def claim_ping(backend, user_id: str) -> tuple[str, dict[str, Any]] | None:
    """Return the newest unread message nobody pinged ``user_id`` about yet, as (peer ID, inbox entry).

    Only the single latest message is returned, and claiming it marks it
    pinged, so several open tabs or a burst of messages produce one ping.
    """

    inbox = load_inbox(backend, user_id)
    waiting = [
        (peer_id, entry)
        for peer_id, entry in inbox.items()
        if entry["unread"] and entry["last_at"] and entry["last_sender_id"] == peer_id
    ]
    if not waiting:
        return None
    peer_id, entry = max(waiting, key=lambda item: item[1]["last_at"])

    payload, etag = _read(backend, _pinged_key(user_id))
    if str(payload.get("last_at") or "") >= entry["last_at"]:
        return None
    if not backend.write_json(_pinged_key(user_id), {"last_at": entry["last_at"]}, etag=etag):
        return None  # Another tab claimed it first.
    return peer_id, entry


def import_message(backend, *, sender_id: str, recipient_id: str, message: str, created_at: str) -> None:
    """Carry an undelivered legacy private dispatch into a thread, keeping its time."""

    text = message.strip()[:MAX_MESSAGE_LENGTH]
    if not text or not sender_id or sender_id == recipient_id:
        return
    entry = {"id": secrets.token_hex(8), "sender_id": sender_id, "message": text, "created_at": created_at}
    key = _thread_key(sender_id, recipient_id)
    for _attempt in range(_WRITE_ATTEMPTS):
        payload, etag = _read(backend, key)
        messages = _clean_messages(payload.get("messages"))
        messages.append(entry)
        messages.sort(key=lambda m: m["created_at"])
        messages = messages[-MAX_MESSAGES_PER_THREAD:]
        document = {"participants": sorted((sender_id, recipient_id)), "messages": messages}
        if backend.write_json(key, document, etag=etag):
            break
    else:
        raise DirectMessageConflict("Conversation changed while importing, please retry")

    _update_inbox(backend, sender_id, lambda threads: _summarize(threads, recipient_id, messages))

    def _for_recipient(threads):
        _summarize(threads, sender_id, messages)
        threads[sender_id]["unread"] = threads[sender_id].get("unread", 0) + 1

    _update_inbox(backend, recipient_id, _for_recipient)


__all__ = [
    "DM_PREFIX",
    "DirectMessageConflict",
    "DirectMessageNotFound",
    "MAX_MESSAGE_LENGTH",
    "append_message",
    "claim_ping",
    "delete_message",
    "import_message",
    "load_inbox",
    "load_thread",
    "mark_read",
    "thread_id",
]
