from __future__ import annotations

from typing import Dict, Set
import time

from storage_spaces import save_json, read_json, ensure_dir
from constants import ROOT_PREFIX
from server_config import get_roles_for_level

ACL_KEY = f"{ROOT_PREFIX}/acl/clearance.json".replace("//", "/")
TEMP_CLEARANCE_KEY = f"{ROOT_PREFIX}/acl/temp_clearance.json".replace("//", "/")


def load_clearance() -> Dict:
    try:
        return read_json(ACL_KEY)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def save_clearance(cfg: Dict) -> None:
    ensure_dir(f"{ROOT_PREFIX}/acl")
    save_json(ACL_KEY, cfg)


def get_required_roles(category: str, item_rel_base: str) -> Set[int]:
    cf = load_clearance()

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


def grant_file_clearance(category: str, item_rel_base: str, role_id: int) -> None:
    cf = load_clearance()
    cf.setdefault(category, {}).setdefault(item_rel_base, [])
    if role_id not in cf[category][item_rel_base]:
        cf[category][item_rel_base].append(role_id)
    save_clearance(cf)


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

    existing = set(get_required_roles(category, item_rel_base))
    added: list[int] = []
    for role_id in target_roles:
        try:
            role_int = int(role_id)
        except (TypeError, ValueError):
            continue
        grant_file_clearance(category, item_rel_base, role_int)
        if role_int not in existing:
            existing.add(role_int)
            added.append(role_int)
    return added


def revoke_file_clearance(category: str, item_rel_base: str, role_id: int) -> None:
    cf = load_clearance()
    if category in cf and item_rel_base in cf[category]:
        cf[category][item_rel_base] = [r for r in cf[category][item_rel_base] if r != role_id]
        if not cf[category][item_rel_base]:
            del cf[category][item_rel_base]
        if not cf[category]:
            del cf[category]
        save_clearance(cf)


def load_temp_clearance() -> Dict:
    try:
        return read_json(TEMP_CLEARANCE_KEY)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def save_temp_clearance(cfg: Dict) -> None:
    ensure_dir(f"{ROOT_PREFIX}/acl")
    save_json(TEMP_CLEARANCE_KEY, cfg)


def grant_temp_clearance(
    category: str, item_rel_base: str, user_id: int, ttl_seconds: int = 600
) -> None:
    cf = load_temp_clearance()
    now = int(time.time())
    entries = cf.setdefault(str(user_id), [])
    entries.append(
        {"category": category, "item": item_rel_base, "expires": now + ttl_seconds}
    )
    save_temp_clearance(cf)


def check_temp_clearance(user_id: int, category: str, item_rel_base: str) -> bool:
    cf = load_temp_clearance()
    now = int(time.time())
    entries = cf.get(str(user_id), [])
    valid = []
    has_access = False
    for entry in entries:
        if entry.get("expires", 0) > now:
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
    save_temp_clearance(cf)
    return has_access
