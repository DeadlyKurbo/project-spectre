"""Persistent website support threads: one conversation per (member, admin) pair."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from owner_portal import OWNER_USER_KEY
from storage_spaces import read_json, write_json

SUPPORT_CHATS_KEY = "owner/support-chats-v1.json"
_MAX_BODY_CHARS = 4000
_MAX_SENDER_LABEL = 120
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


def thread_storage_key(member_id: str, target_admin_id: str) -> str:
    m = _normalise_user_id(member_id)
    a = _normalise_user_id(target_admin_id)
    if not m or not a:
        raise ValueError("member_id and target_admin_id must be numeric Discord IDs")
    return f"{m}:{a}"


def parse_thread_storage_key(key: str) -> tuple[str | None, str | None]:
    raw = str(key).strip()
    if ":" in raw:
        left, _, right = raw.partition(":")
        return _normalise_user_id(left), _normalise_user_id(right)
    return _normalise_user_id(raw), None


def _migrate_v1_threads(threads: dict[str, Any]) -> dict[str, Any]:
    """Legacy keys were member-id only; attach to owner as default admin."""

    owner = _normalise_user_id(OWNER_USER_KEY) or ""
    out: dict[str, Any] = {}
    for k, v in threads.items():
        if not isinstance(v, dict):
            continue
        ks = str(k).strip()
        if ":" in ks:
            out[ks] = v
            continue
        uid = _normalise_user_id(k)
        if not uid or not owner:
            continue
        nk = f"{uid}:{owner}"
        if nk in out:
            merged = _merge_thread_dicts(out[nk], v)
            out[nk] = merged
        else:
            copy_v = dict(v)
            if not str(copy_v.get("target_admin_id") or "").strip():
                copy_v["target_admin_id"] = owner
            out[nk] = copy_v
    return out


def _merge_thread_dicts(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    msgs_a = _coerce_messages(a.get("messages"))
    msgs_b = _coerce_messages(b.get("messages"))
    merged = msgs_a + msgs_b
    merged.sort(key=lambda m: str(m.get("createdAt") or m.get("created_at") or ""))
    if len(merged) > _MAX_MESSAGES_PER_THREAD:
        merged = merged[-_MAX_MESSAGES_PER_THREAD:]
    created = str(a.get("created_at") or b.get("created_at") or "")
    ua, ub = str(a.get("updated_at") or ""), str(b.get("updated_at") or "")
    return {
        "created_at": created,
        "updated_at": max(ua, ub),
        "user_label": str(a.get("user_label") or b.get("user_label") or ""),
        "target_admin_id": str(a.get("target_admin_id") or b.get("target_admin_id") or ""),
        "messages": merged,
    }


def load_support_store() -> dict[str, Any]:
    with _store_lock:
        try:
            raw = read_json(SUPPORT_CHATS_KEY)
        except FileNotFoundError:
            return {"version": 2, "threads": {}}
        if not isinstance(raw, dict):
            return {"version": 2, "threads": {}}
        threads = raw.get("threads")
        if not isinstance(threads, dict):
            threads = {}
        version = int(raw.get("version") or 1)
        if version < 2:
            threads = _migrate_v1_threads(threads)
            payload = {"version": 2, "threads": threads}
            write_json(SUPPORT_CHATS_KEY, payload)
            return payload
        return {"version": 2, "threads": threads}


def _persist_store(store: dict[str, Any]) -> None:
    payload = {"version": 2, "threads": store.get("threads") or {}}
    write_json(SUPPORT_CHATS_KEY, payload)


def get_thread_for_pair(member_id: str, target_admin_id: str) -> dict[str, Any] | None:
    m = _normalise_user_id(member_id)
    a = _normalise_user_id(target_admin_id)
    if not m or not a:
        return None
    key = f"{m}:{a}"
    store = load_support_store()
    threads: dict[str, Any] = store.get("threads") or {}
    raw = threads.get(key)
    if not isinstance(raw, dict):
        return None
    return _serialise_thread(key, raw)


def list_thread_summaries() -> list[dict[str, Any]]:
    store = load_support_store()
    threads: dict[str, Any] = store.get("threads") or {}
    rows: list[dict[str, Any]] = []
    for tid, raw in threads.items():
        if not isinstance(raw, dict):
            continue
        member_id, admin_id = parse_thread_storage_key(str(tid))
        if not member_id or not admin_id:
            continue
        messages = _coerce_messages(raw.get("messages"))
        last = messages[-1] if messages else None
        preview = ""
        last_at = raw.get("updated_at") or raw.get("created_at") or ""
        if last:
            preview = str(last.get("body") or "")[:140]
            last_at = str(last.get("createdAt") or last.get("created_at") or last_at)
        rows.append(
            {
                "threadKey": str(tid),
                "threadUserId": member_id,
                "targetAdminId": admin_id,
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
    member_id: str,
    target_admin_id: str,
    sender_id: str,
    sender_label: str,
    is_staff: bool,
    body: str,
) -> tuple[dict[str, Any], str]:
    """Append to the (member, admin) thread. Returns (message dict, thread_storage_key)."""

    mid = _normalise_user_id(member_id)
    aid = _normalise_user_id(target_admin_id)
    sid = _normalise_user_id(sender_id)
    if not mid or not aid or not sid:
        raise ValueError("member_id, target_admin_id, and sender_id must be numeric Discord IDs")
    text = _normalise_body(body)
    if not text:
        raise ValueError("Message body is required")

    label = str(sender_label or "").strip()
    if len(label) > _MAX_SENDER_LABEL:
        label = label[:_MAX_SENDER_LABEL].rstrip()

    thread_key = f"{mid}:{aid}"
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
        thread = threads.get(thread_key)
        if not isinstance(thread, dict):
            thread = {
                "created_at": now,
                "updated_at": now,
                "user_label": "" if is_staff else label,
                "target_admin_id": aid,
                "messages": [],
            }
            threads[thread_key] = thread
        else:
            if not is_staff and not str(thread.get("user_label") or "").strip():
                thread["user_label"] = label
            thread["target_admin_id"] = str(thread.get("target_admin_id") or aid)
        messages = _coerce_messages(thread.get("messages"))
        messages.append(entry)
        if len(messages) > _MAX_MESSAGES_PER_THREAD:
            messages = messages[-_MAX_MESSAGES_PER_THREAD:]
        thread["messages"] = messages
        thread["updated_at"] = now
        _persist_store(store)

    return entry, thread_key


def delete_thread_by_pair(member_id: str, target_admin_id: str) -> bool:
    mid = _normalise_user_id(member_id)
    aid = _normalise_user_id(target_admin_id)
    if not mid or not aid:
        return False
    thread_key = f"{mid}:{aid}"
    with _store_lock:
        store = load_support_store()
        threads: dict[str, Any] = store.get("threads") or {}
        if thread_key not in threads:
            return False
        del threads[thread_key]
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


def _serialise_thread(thread_key: str, raw: dict[str, Any]) -> dict[str, Any]:
    member_id, admin_id = parse_thread_storage_key(thread_key)
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
        "threadKey": thread_key,
        "threadUserId": member_id or "",
        "targetAdminId": admin_id or str(raw.get("target_admin_id") or ""),
        "userLabel": str(raw.get("user_label") or "Member"),
        "createdAt": str(raw.get("created_at") or ""),
        "updatedAt": str(raw.get("updated_at") or ""),
        "messages": cleaned,
    }
