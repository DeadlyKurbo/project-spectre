from __future__ import annotations

from typing import Dict, Set
import time

from storage_spaces import save_json, read_json, ensure_dir, get_root_prefix


def _acl_key() -> str:
    """Return the storage key for the clearance mapping.

    The key is derived from the *current* storage root so different archives can
    maintain completely isolated access control lists.  Section Zero, for
    example, operates under its own ``SECTION_ZERO_ROOT_PREFIX`` and therefore
    receives a separate ``acl/clearance.json`` file.
    """

    return f"{get_root_prefix()}/acl/clearance.json".replace("//", "/")


def _temp_clearance_key() -> str:
    """Return the storage key for temporary access overrides."""

    return f"{get_root_prefix()}/acl/temp_clearance.json".replace("//", "/")


def load_clearance() -> Dict:
    """Load the persistent clearance mapping for the current archive."""

    try:
        return read_json(_acl_key())
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def save_clearance(cfg: Dict) -> None:
    """Persist the clearance mapping for the active archive."""

    ensure_dir(f"{get_root_prefix()}/acl")
    save_json(_acl_key(), cfg)


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
        return read_json(_temp_clearance_key())
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def save_temp_clearance(cfg: Dict) -> None:
    ensure_dir(f"{get_root_prefix()}/acl")
    save_json(_temp_clearance_key(), cfg)


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
