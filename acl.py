from __future__ import annotations

from typing import Dict, Set
import time

from storage_spaces import save_json, read_json, ensure_dir
from constants import ROOT_PREFIX
from server_config import get_roles_for_level, get_server_config


def _acl_root_prefix(guild_id: int | None) -> str:
    """Return the storage root for ACL files. Must match the guild's archive root."""
    if guild_id is None:
        return ROOT_PREFIX
    cfg = get_server_config(guild_id)
    root = cfg.get("ROOT_PREFIX", ROOT_PREFIX) if isinstance(cfg, dict) else ROOT_PREFIX
    if isinstance(root, str) and root.strip().strip("/"):
        return root.strip().strip("/")
    return f"{ROOT_PREFIX}/{guild_id}"


def _acl_key(guild_id: int | None) -> str:
    prefix = _acl_root_prefix(guild_id)
    return f"{prefix}/acl/clearance.json".replace("//", "/")


def _temp_clearance_key(guild_id: int | None) -> str:
    prefix = _acl_root_prefix(guild_id)
    return f"{prefix}/acl/temp_clearance.json".replace("//", "/")


# Legacy module-level keys for backward compatibility when guild_id is not yet threaded through
ACL_KEY = f"{ROOT_PREFIX}/acl/clearance.json".replace("//", "/")
TEMP_CLEARANCE_KEY = f"{ROOT_PREFIX}/acl/temp_clearance.json".replace("//", "/")


def load_clearance(guild_id: int | None = None) -> Dict:
    key = _acl_key(guild_id)
    try:
        return read_json(key)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def save_clearance(cfg: Dict, guild_id: int | None = None) -> None:
    prefix = _acl_root_prefix(guild_id)
    ensure_dir(f"{prefix}/acl")
    save_json(_acl_key(guild_id), cfg)


def get_required_roles(category: str, item_rel_base: str, guild_id: int | None = None) -> Set[int]:
    cf = load_clearance(guild_id)

    # Perform a case-insensitive lookup for both the category and item name
    cat_key = next((c for c in cf if c.lower() == category.lower()), None)
    if not cat_key:
        return set()

    items = cf.get(cat_key, {})
    item_key = next((i for i in items if i.lower() == item_rel_base.lower()), None)
    if not item_key:
        return set()

    roles = items.get(item_key, [])
    return {int(r) for r in roles}


def grant_file_clearance(
    category: str, item_rel_base: str, role_id: int, guild_id: int | None = None
) -> None:
    cf = load_clearance(guild_id)
    cf.setdefault(category, {}).setdefault(item_rel_base, [])
    if role_id not in cf[category][item_rel_base]:
        cf[category][item_rel_base].append(role_id)
    save_clearance(cf, guild_id)


def grant_level_clearance(
    category: str, item_rel_base: str, level: int, guild_id: int | None = None
) -> list[int]:
    """Grant all roles mapped to a clearance ``level`` for ``category/item``.

    Returns a list of role IDs that were newly granted access.
    """

    try:
        level_int = int(level)
    except (TypeError, ValueError):
        return []

    target_roles = get_roles_for_level(level_int, guild_id)
    if not target_roles:
        return []

    existing = set(get_required_roles(category, item_rel_base, guild_id))
    added: list[int] = []
    for role_id in target_roles:
        try:
            role_int = int(role_id)
        except (TypeError, ValueError):
            continue
        grant_file_clearance(category, item_rel_base, role_int, guild_id)
        if role_int not in existing:
            existing.add(role_int)
            added.append(role_int)
    return added


def revoke_file_clearance(
    category: str, item_rel_base: str, role_id: int, guild_id: int | None = None
) -> None:
    cf = load_clearance(guild_id)
    if category in cf and item_rel_base in cf[category]:
        cf[category][item_rel_base] = [r for r in cf[category][item_rel_base] if r != role_id]
        if not cf[category][item_rel_base]:
            del cf[category][item_rel_base]
        if not cf[category]:
            del cf[category]
        save_clearance(cf, guild_id)


def load_temp_clearance(guild_id: int | None = None) -> Dict:
    key = _temp_clearance_key(guild_id)
    try:
        return read_json(key)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def save_temp_clearance(cfg: Dict, guild_id: int | None = None) -> None:
    prefix = _acl_root_prefix(guild_id)
    ensure_dir(f"{prefix}/acl")
    save_json(_temp_clearance_key(guild_id), cfg)


def grant_temp_clearance(
    category: str,
    item_rel_base: str,
    user_id: int,
    ttl_seconds: int = 600,
    guild_id: int | None = None,
) -> None:
    cf = load_temp_clearance(guild_id)
    now = int(time.time())
    entries = cf.setdefault(str(user_id), [])
    entries.append(
        {"category": category, "item": item_rel_base, "expires": now + ttl_seconds}
    )
    save_temp_clearance(cf, guild_id)


def grant_one_time_clearance(
    category: str, item_rel_base: str, user_id: int, guild_id: int | None = None
) -> None:
    """Grant ONE-TIME access to a specific file. Consumed on first successful access."""
    cf = load_temp_clearance(guild_id)
    entries = cf.setdefault(str(user_id), [])
    entries.append(
        {"category": category, "item": item_rel_base, "one_time": True}
    )
    save_temp_clearance(cf, guild_id)


def check_temp_clearance(
    user_id: int, category: str, item_rel_base: str, guild_id: int | None = None
) -> bool:
    cf = load_temp_clearance(guild_id)
    now = int(time.time())
    entries = cf.get(str(user_id), [])
    valid = []
    has_access = False
    for entry in entries:
        if entry.get("one_time"):
            if (
                entry.get("category") == category
                and entry.get("item") == item_rel_base
            ):
                has_access = True
                # Consume one-time entry; do not add to valid
            else:
                valid.append(entry)
        elif entry.get("expires", 0) > now:
            if (
                entry.get("category") == category
                and entry.get("item") == item_rel_base
            ):
                has_access = True
            valid.append(entry)
    if valid:
        cf[str(user_id)] = valid
    elif str(user_id) in cf:
        del cf[str(user_id)]
    save_temp_clearance(cf, guild_id)
    return has_access
