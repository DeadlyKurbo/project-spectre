"""Director-facing helpers for full archive control.

This module exposes a high-level view of every dossier file so the director
can audit, edit, move, or delete content without jumping between interfaces.
Assignments to automation bots are tracked in a lightweight JSON registry to
keep the metadata alongside the files themselves without modifying dossier
contents.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from dossier import (
    list_archived_categories,
    list_categories,
    list_items_recursive,
    load_dossier_pages,
    move_dossier_file,
    remove_dossier_file,
    resolve_dossier_key,
    save_dossier_pages,
)
from storage_spaces import read_json, write_json


_ASSIGNMENTS_KEY = "director/file-assignments.json"


@dataclass(slots=True)
class DirectorFileRecord:
    """Represents a single dossier file with director metadata."""

    category: str
    item: str
    key: str
    extension: str
    page_count: int
    assigned_bot: str | None = None
    last_actor: str | None = None
    updated_at: str | None = None

    def to_payload(self, *, pages: list[str] | None = None) -> dict:
        payload = {
            "category": self.category,
            "item": self.item,
            "key": self.key,
            "extension": self.extension,
            "page_count": self.page_count,
            "assigned_bot": self.assigned_bot,
            "last_actor": self.last_actor,
            "updated_at": self.updated_at,
        }
        if pages is not None:
            payload["pages"] = pages
        return payload


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_assignments() -> dict:
    try:
        data = read_json(_ASSIGNMENTS_KEY)
    except FileNotFoundError:
        return {}
    return data if isinstance(data, dict) else {}


def _save_assignments(assignments: dict) -> None:
    write_json(_ASSIGNMENTS_KEY, assignments)


def _assignment_for(key: str) -> tuple[str | None, str | None, str | None]:
    data = _load_assignments().get(key)
    if not isinstance(data, dict):
        return None, None, None
    bot = str(data.get("bot") or "").strip() or None
    actor = str(data.get("actor") or "").strip() or None
    updated_at = str(data.get("updated_at") or "").strip() or None
    return bot, actor, updated_at


def _record_assignment(key: str, bot: str | None, actor: str | None) -> tuple[str | None, str | None, str | None]:
    assignments = _load_assignments()
    if bot:
        assignments[key] = {
            "bot": bot,
            "actor": actor or "Unknown operator",
            "updated_at": _now_iso(),
        }
    elif key in assignments:
        assignments.pop(key, None)
    _save_assignments(assignments)
    stored_bot, stored_actor, updated_at = _assignment_for(key)
    return stored_bot, stored_actor, updated_at


def list_director_categories(guild_id: int | None = None) -> list[str]:
    categories: list[str] = []
    categories.extend(list_categories(guild_id=guild_id))
    categories.extend([f"_archived/{name}" for name in list_archived_categories(guild_id=guild_id)])
    return categories


def _all_dossier_items(guild_id: int | None = None) -> Iterable[tuple[str, str]]:
    for category in list_director_categories(guild_id=guild_id):
        for item in list_items_recursive(category, guild_id=guild_id):
            yield category, item


def build_file_index(guild_id: int | None = None) -> list[DirectorFileRecord]:
    assignments = _load_assignments()
    records: list[DirectorFileRecord] = []

    for category, item in _all_dossier_items(guild_id=guild_id):
        try:
            key, ext = resolve_dossier_key(category, item, guild_id=guild_id)
            pages = load_dossier_pages(category, item, guild_id=guild_id)
        except FileNotFoundError:
            continue
        except Exception:
            continue

        assigned = assignments.get(key) if isinstance(assignments.get(key), dict) else {}
        assigned_bot = str(assigned.get("bot") or "").strip() or None
        records.append(
            DirectorFileRecord(
                category=category,
                item=item,
                key=key,
                extension=ext,
                page_count=len(pages),
                assigned_bot=assigned_bot,
                last_actor=str(assigned.get("actor") or "").strip() or None,
                updated_at=str(assigned.get("updated_at") or "").strip() or None,
            )
        )

    return sorted(records, key=lambda rec: (rec.category.lower(), rec.item.lower()))


def load_file_detail(category: str, item: str, guild_id: int | None = None) -> tuple[DirectorFileRecord, list[str]]:
    key, ext = resolve_dossier_key(category, item, guild_id=guild_id)
    pages = load_dossier_pages(category, item, guild_id=guild_id)
    assigned_bot, actor, updated_at = _assignment_for(key)

    record = DirectorFileRecord(
        category=category,
        item=item,
        key=key,
        extension=ext,
        page_count=len(pages),
        assigned_bot=assigned_bot,
        last_actor=actor,
        updated_at=updated_at,
    )
    return record, pages


def update_file(
    category: str,
    item: str,
    pages: list[str],
    *,
    new_category: str | None = None,
    new_item: str | None = None,
    assigned_bot: str | None = None,
    actor: str | None = None,
    guild_id: int | None = None,
) -> tuple[DirectorFileRecord, list[str]]:
    key, ext = resolve_dossier_key(category, item, guild_id=guild_id)
    save_dossier_pages(category, item, pages, extension=ext, guild_id=guild_id)

    dest_category = new_category.strip() if isinstance(new_category, str) else category
    dest_item = new_item.strip() if isinstance(new_item, str) else item
    dest_category = dest_category or category
    dest_item = dest_item or item

    if dest_category != category or dest_item != item:
        key = move_dossier_file(category, item, dest_category, dest_item, guild_id=guild_id)
        category = dest_category
        item = dest_item

    bot = assigned_bot.strip() if isinstance(assigned_bot, str) else None
    assigned_bot, _actor_name, _updated_at = _record_assignment(key, bot, actor)

    return load_file_detail(category, item, guild_id=guild_id)


def remove_file(category: str, item: str, *, guild_id: int | None = None) -> str:
    key, _ = resolve_dossier_key(category, item, guild_id=guild_id)
    remove_dossier_file(category, item, guild_id=guild_id)

    assignments = _load_assignments()
    if key in assignments:
        assignments.pop(key, None)
        _save_assignments(assignments)
    return key


__all__ = [
    "DirectorFileRecord",
    "build_file_index",
    "list_director_categories",
    "load_file_detail",
    "remove_file",
    "update_file",
]
