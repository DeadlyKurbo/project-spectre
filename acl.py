from __future__ import annotations

from typing import Dict, Set

from storage_spaces import save_json, read_json, ensure_dir
from constants import ROOT_PREFIX

ACL_KEY = f"{ROOT_PREFIX}/acl/clearance.json".replace("//", "/")


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
    roles = cf.get(category, {}).get(item_rel_base, [])
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
