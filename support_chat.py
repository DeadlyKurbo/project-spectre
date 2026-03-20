"""Persistent website support threads between fleet members and portal admins."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from storage_spaces import read_json, write_json

SUPPORT_CHATS_KEY = "owner/support-chats-v1.json"
_MAX_BODY_CHARS = 4000
_MAX_SENDER_LABEL = 120
# High ceiling to keep history usable without unbounded disk growth from abuse.
_MAX_MESSAGES_PER_THREAD = 15000

_store_lock = threading.RLock()


def _normalise_user_id(value: str | int | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned.isdigit():
        return None
    return cleaned


def _normalise_body(text: str | None) -> str:
    if not text:
        return ""
    cleaned = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(cleaned) > _MAX_BODY_CHARS:
        cleaned = cleaned[:_MAX_BODY_CHARS].rstrip()
    return cleaned


def load_support_store() -> dict[str, Any]:
    """Return the full persisted document (mutate only under ``_store_lock`` in this module)."""

    with _store_lock:
        try:
            raw = read_json(SUPPORT_CHATS_KEY)
        except FileNotFoundError:
            return {"version": 1, "threads": {}}
        if not isinstance(raw, dict):
            return {"version": 1, "threads": {}}
        threads = raw.get("threads")
        if not isinstance(threads, dict):
            threads = {}
        return {"version": 1, "threads": threads}


def _persist_store(store: dict[str, Any]) -> None:
    payload = {"version": int(store.get("version") or 1), "threads": store.get("threads") or {}}
    write_json(SUPPORT_CHATS_KEY, payload)


def get_thread_for_user(thread_user_id: str) -> dict[str, Any] | None:
    """Return a copy of the thread for ``thread_user_id`` or ``None``."""

    uid = _normalise_user_id(thread_user_id)
    if not uid:
        return None
    store = load_support_store()
    threads: dict[str, Any] = store.get("threads") or {}
    raw = threads.get(uid)
    if not isinstance(raw, dict):
        return None
    return _serialise_thread(uid, raw)


def list_thread_summaries() -> list[dict[str, Any]]:
    """Summaries for admin inbox, newest activity first."""

    store = load_support_store()
    threads: dict[str, Any] = store.get("threads") or {}
    rows: list[dict[str, Any]] = []
    for tid, raw in threads.items():
        uid = _normalise_user_id(tid)
        if not uid or not isinstance(raw, dict):
            continue
        messages = _coerce_messages(raw.get("messages"))
        last = messages[-1] if messages else None
        preview = ""
        last_at = raw.get("updated_at") or raw.get("created_at") or ""
        if last:
            preview = str(last.get("body") or "")[:140]
            last_at = str(last.get("created_at") or last_at)
        rows.append(
            {
                "threadUserId": uid,
                "userLabel": str(raw.get("user_label") or "Member"),
                "messageCount": len(messages),
                "updatedAt": last_at,
                "preview": preview,
            }
        )
    rows.sort(key=lambda r: str(r.get("updatedAt") or ""), reverse=True)
    return rows


def append_message(
    *,
    thread_user_id: str,
    sender_id: str,
    sender_label: str,
    is_staff: bool,
    body: str,
) -> dict[str, Any]:
    """Append a message to ``thread_user_id``'s thread and persist. Returns the message dict."""

    tid = _normalise_user_id(thread_user_id)
    sid = _normalise_user_id(sender_id)
    if not tid or not sid:
        raise ValueError("thread_user_id and sender_id must be numeric Discord IDs")
    text = _normalise_body(body)
    if not text:
        raise ValueError("Message body is required")

    label = str(sender_label or "").strip()
    if len(label) > _MAX_SENDER_LABEL:
        label = label[:_MAX_SENDER_LABEL].rstrip()

    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "id": str(uuid.uuid4()),
        "senderId": sid,
        "senderLabel": label or ("Staff" if is_staff else "Member"),
        "isStaff": bool(is_staff),
        "body": text,
        "createdAt": now,
    }

    with _store_lock:
        store = load_support_store()
        threads: dict[str, Any] = store.setdefault("threads", {})
        thread = threads.get(tid)
        if not isinstance(thread, dict):
            thread = {
                "created_at": now,
                "updated_at": now,
                "user_label": "" if is_staff else label,
                "messages": [],
            }
            threads[tid] = thread
        else:
            if not is_staff and not str(thread.get("user_label") or "").strip():
                thread["user_label"] = label
        messages = _coerce_messages(thread.get("messages"))
        messages.append(entry)
        if len(messages) > _MAX_MESSAGES_PER_THREAD:
            messages = messages[-_MAX_MESSAGES_PER_THREAD:]
        thread["messages"] = messages
        thread["updated_at"] = now
        _persist_store(store)

    return entry


def delete_thread(thread_user_id: str) -> bool:
    """Remove a thread entirely. Returns ``True`` if a thread was deleted."""

    tid = _normalise_user_id(thread_user_id)
    if not tid:
        return False
    with _store_lock:
        store = load_support_store()
        threads: dict[str, Any] = store.get("threads") or {}
        if tid not in threads:
            return False
        del threads[tid]
        _persist_store(store)
    return True


def _coerce_messages(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
    return out


def _serialise_thread(thread_user_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    messages = _coerce_messages(raw.get("messages"))
    cleaned: list[dict[str, Any]] = []
    for m in messages:
        cleaned.append(
            {
                "id": str(m.get("id") or ""),
                "senderId": str(m.get("senderId") or m.get("sender_id") or ""),
                "senderLabel": str(m.get("senderLabel") or m.get("sender_label") or "Unknown"),
                "isStaff": bool(m.get("isStaff") if "isStaff" in m else m.get("is_staff")),
                "body": str(m.get("body") or ""),
                "createdAt": str(m.get("createdAt") or m.get("created_at") or ""),
            }
        )
    return {
        "threadUserId": thread_user_id,
        "userLabel": str(raw.get("user_label") or "Member"),
        "createdAt": str(raw.get("created_at") or ""),
        "updatedAt": str(raw.get("updated_at") or ""),
        "messages": cleaned,
    }
