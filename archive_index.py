"""Cached, single-pass index of a guild's dossier files for the web archive.

The helpers in :mod:`dossier` resolve one item at a time for the Discord menus,
which costs several storage listings per file. The website needs every file at
once, so this module walks each archive root with one recursive listing,
resolves categories the same way :func:`dossier.enumerate_dossier_files` does,
and keeps the result for a short time so filtering, searching and opening
dossiers never re-scan storage.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

import acl
import constants
import dossier
import server_config
import storage_spaces
import utils

INDEX_TTL_SECONDS = 60.0
# A key missing from the index triggers one rebuild (it may be brand new), but
# never more often than this, so unknown keys cannot hammer storage.
MISS_REBUILD_MIN_AGE_SECONDS = 5.0
CLEARANCE_LEVELS = (1, 2, 3, 4, 5, 6)
_DOSSIER_EXTENSIONS = (".json", ".txt")


@dataclass
class ArchiveIndex:
    guild_id: int
    built_at: float
    entries: list[dict[str, Any]]
    roots: list[str]
    category_labels: dict[str, str] = field(default_factory=dict)

    def find(self, key: str) -> dict[str, Any] | None:
        target = str(key or "").strip().lstrip("/")
        if not target:
            return None
        return next((entry for entry in self.entries if entry["key"] == target), None)


_cache: dict[int, ArchiveIndex] = {}
_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(guild_id: int) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(guild_id)
        if lock is None:
            lock = _locks[guild_id] = threading.Lock()
        return lock


def _strip_ext(name: str) -> str:
    low = name.lower()
    for ext in _DOSSIER_EXTENSIONS:
        if low.endswith(ext):
            return name[: -len(ext)]
    return name


def _iso(timestamp: float | None) -> str:
    if not timestamp:
        return ""
    try:
        return datetime.fromtimestamp(float(timestamp), timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _category_label(category: str, overrides: Mapping[str, str]) -> str:
    """Mirror :func:`utils.get_category_label` without a storage read per call."""

    key = category.strip().lower().replace(" ", "_")
    if key in overrides:
        return overrides[key]
    label_map = {slug.lower(): label for slug, label in constants.CATEGORY_ORDER}
    return label_map.get(category.lower(), category.replace("_", " ").title())


def build_index(guild_id: int) -> ArchiveIndex:
    gid = int(guild_id)
    configured: dict[str, str] = {}
    for slug, _label in constants.CATEGORY_ORDER:
        configured.setdefault(dossier._normalize_category(slug), slug)

    roots = dossier._archive_root_prefixes(gid)
    category_names: dict[tuple[bool, str], str] = {}
    chosen: dict[tuple[bool, str, str], dict[str, Any]] = {}

    for root in roots:
        for rel, size, modified in storage_spaces.list_tree(root):
            parts = [segment for segment in rel.split("/") if segment]
            archived = bool(parts) and parts[0] == "_archived"
            if archived:
                parts = parts[1:]
            if len(parts) < 2:
                continue
            category_dir, filename = parts[0], parts[-1]
            if category_dir.startswith("_") or not filename.lower().endswith(_DOSSIER_EXTENSIONS):
                continue
            normalized = dossier._normalize_category(category_dir)
            if not normalized or (not archived and normalized == "acl"):
                continue

            category = category_names.setdefault(
                (archived, normalized), configured.get(normalized, category_dir)
            )
            item = _strip_ext("/".join(parts[1:]))
            ext = ".json" if filename.lower().endswith(".json") else ".txt"
            identity = (archived, normalized, item)
            existing = chosen.get(identity)
            # Same precedence as dossier._find_existing_item_key: the first root
            # wins, and within a folder .json beats .txt.
            if existing is not None and not (
                existing["root"] == root and ext == ".json" and existing["ext"] != ".json"
            ):
                continue
            chosen[identity] = {
                "key": f"{root}/{rel}".strip("/") if root else rel.strip("/"),
                "root": root,
                "category": category,
                "name": item,
                "ext": ext,
                "archived": archived,
                "size": int(size or 0),
                "updated_at": _iso(modified),
            }

    entries = sorted(
        chosen.values(),
        key=lambda entry: (entry["archived"], entry["category"].lower(), entry["name"].lower()),
    )
    overrides = utils._get_guild_category_label_overrides(gid)
    labels = {entry["category"]: _category_label(entry["category"], overrides) for entry in entries}
    return ArchiveIndex(guild_id=gid, built_at=time.time(), entries=entries, roots=list(roots), category_labels=labels)


def get_index(guild_id: int, *, force: bool = False) -> ArchiveIndex:
    """Return the cached index, rebuilding it when stale or when ``force`` is set."""

    gid = int(guild_id)
    requested_at = time.time()
    cached = _cache.get(gid)
    if cached and not force and requested_at - cached.built_at < INDEX_TTL_SECONDS:
        return cached
    with _lock_for(gid):
        cached = _cache.get(gid)
        # Another request may have rebuilt it while this one waited for the lock.
        if cached and (cached.built_at >= requested_at or (
            not force and time.time() - cached.built_at < INDEX_TTL_SECONDS
        )):
            return cached
        index = build_index(gid)
        _cache[gid] = index
        return index


def find_entry(guild_id: int, key: str) -> dict[str, Any] | None:
    index = get_index(guild_id)
    entry = index.find(key)
    if entry is None and time.time() - index.built_at >= MISS_REBUILD_MIN_AGE_SECONDS:
        entry = get_index(guild_id, force=True).find(key)
    return entry


def invalidate(guild_id: int | None = None) -> None:
    if guild_id is None:
        _cache.clear()
        return
    try:
        _cache.pop(int(guild_id), None)
    except (TypeError, ValueError):
        return


@dataclass
class AccessResolver:
    """Per-request clearance lookups built from one read of the ACL file."""

    table: dict[str, dict[str, set[int]]]
    role_levels: dict[int, int]
    level_names: dict[int, str]
    level_roles: dict[int, set[int]] = field(default_factory=dict)
    # Higher levels also open lower levels' files unless the server uses strict levels.
    levels_stack: bool = True

    def required_roles(self, category: str, item: str) -> set[int]:
        return set(self.table.get(str(category).lower(), {}).get(str(item).lower(), set()))

    def level_for(self, roles: set[int]) -> int | None:
        """Clearance shown on a file: the lowest level among its required roles."""
        levels = [self.role_levels[role] for role in roles if role in self.role_levels]
        return min(levels) if levels else None

    def member_level(self, roles: set[int]) -> int | None:
        """Clearance shown for a member: the highest level whose roles they hold."""
        levels = [level for level, level_roles in self.level_roles.items() if level_roles & roles]
        return max(levels) if levels else None

    def allows(self, member_roles: set[int], required_roles: set[int]) -> bool:
        """Mirror server_config.roles_have_clearance with this request's lookups."""
        if member_roles & required_roles:
            return True
        if not required_roles or not self.levels_stack:
            return False
        file_level = self.level_for(required_roles)
        member_level = self.member_level(member_roles)
        return file_level is not None and member_level is not None and member_level >= file_level

    def level_label(self, level: int | None) -> str:
        if not level:
            return ""
        return self.level_names.get(level) or f"Level {level}"


def build_access_resolver(guild_id: int) -> AccessResolver:
    gid = int(guild_id)
    table: dict[str, dict[str, set[int]]] = {}
    clearance = acl.load_clearance(gid)
    if isinstance(clearance, Mapping):
        # First case-insensitive match wins, as in acl.get_required_roles.
        for category, items in clearance.items():
            bucket_key = str(category).lower()
            if bucket_key in table or not isinstance(items, Mapping):
                continue
            bucket: dict[str, set[int]] = {}
            for item, roles in items.items():
                item_key = str(item).lower()
                if item_key in bucket:
                    continue
                parsed: set[int] = set()
                for role in roles if isinstance(roles, (list, tuple, set)) else []:
                    try:
                        parsed.add(int(role))
                    except (TypeError, ValueError):
                        continue
                bucket[item_key] = parsed
            table[bucket_key] = bucket

    role_levels: dict[int, int] = {}
    level_roles: dict[int, set[int]] = {}
    for level in CLEARANCE_LEVELS:
        for role in server_config.get_roles_for_level(level, gid):
            try:
                role_id = int(role)
            except (TypeError, ValueError):
                continue
            if not role_id:
                continue
            level_roles.setdefault(level, set()).add(role_id)
            role_levels.setdefault(role_id, level)

    level_names: dict[int, str] = {}
    try:
        configured_levels = server_config.get_clearance_levels(gid)
    except Exception:
        configured_levels = {}
    for level, entry in (configured_levels or {}).items():
        name = entry.get("name") if isinstance(entry, Mapping) else None
        if isinstance(name, str) and name.strip():
            try:
                level_names[int(level)] = name.strip()
            except (TypeError, ValueError):
                continue

    return AccessResolver(
        table=table,
        role_levels=role_levels,
        level_names=level_names,
        level_roles=level_roles,
        levels_stack=server_config.clearance_levels_stack(gid),
    )
