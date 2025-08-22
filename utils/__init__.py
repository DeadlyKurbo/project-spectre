"""Utility helpers exposed for tests and runtime."""

from __future__ import annotations

import json
import os
from typing import Dict, Set

# Base directory for local dossier storage. Tests may monkeypatch these.
BASE_DIR = os.getcwd()
DOSSIERS_DIR = os.path.join(BASE_DIR, "dossiers")
# Clearance data lives under the `acl` subdirectory inside the dossiers folder.
# The previous path pointed directly to `dossiers/clearance.json`, which meant
# the application could not see the actual clearance file.  Including the
# `acl` layer here aligns the code with the on-disk layout
# (`dossiers/acl/clearance.json`).
CLEARANCE_FILE = os.path.join(DOSSIERS_DIR, "acl", "clearance.json")

# ---------------------------------------------------------------------------
# Clearance helpers
# ---------------------------------------------------------------------------

def _ensure_parent(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)

def load_clearance() -> Dict:
    try:
        with open(CLEARANCE_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}

def save_clearance(cfg: Dict) -> None:
    _ensure_parent(CLEARANCE_FILE)
    with open(CLEARANCE_FILE, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)

def get_required_roles(category: str, item_rel_base: str) -> Set[int]:
    cfg = load_clearance()
    roles = cfg.get(category, {}).get(item_rel_base, [])
    return {int(r) for r in roles}

def grant_file_clearance(category: str, item_rel_base: str, role_id: int) -> None:
    cfg = load_clearance()
    cfg.setdefault(category, {}).setdefault(item_rel_base, [])
    if role_id not in cfg[category][item_rel_base]:
        cfg[category][item_rel_base].append(int(role_id))
    save_clearance(cfg)

def revoke_file_clearance(category: str, item_rel_base: str, role_id: int) -> None:
    cfg = load_clearance()
    if category in cfg and item_rel_base in cfg[category]:
        cfg[category][item_rel_base] = [int(r) for r in cfg[category][item_rel_base] if int(r) != int(role_id)]
        if not cfg[category][item_rel_base]:
            del cfg[category][item_rel_base]
        if category in cfg and not cfg[category]:
            del cfg[category]
        save_clearance(cfg)

def set_category_clearance(category: str, roles: list[int]) -> None:
    cfg = load_clearance()
    items = list_items(category)
    cfg.setdefault(category, {})
    for item in items:
        cfg[category][item] = [int(r) for r in roles]
    save_clearance(cfg)

def reset_category_clearance(category: str) -> None:
    cfg = load_clearance()
    items = list_items(category)
    cfg[category] = {name: [] for name in items}
    save_clearance(cfg)

def set_files_clearance(changes: Dict[str, list[str]], roles: list[int]) -> None:
    cfg = load_clearance()
    for cat, items in changes.items():
        cfg.setdefault(cat, {})
        for item in items:
            cfg[cat][item] = [int(r) for r in roles]
    save_clearance(cfg)

# ---------------------------------------------------------------------------
# Dossier helpers (re-exported from file_ops)
# ---------------------------------------------------------------------------
from .file_ops import (
    list_categories,
    list_items_recursive,
    create_dossier_file,
    remove_dossier_file,
    update_dossier_raw,
    patch_dossier_json_field,
    has_access,
)

def create_dossier_with_clearance(category: str, item_rel: str, content: str, role_id: int) -> str:
    path = create_dossier_file(category, item_rel, content)
    grant_file_clearance(category, item_rel.strip().strip("/"), int(role_id))
    return path

def list_items(category: str) -> list[str]:
    items = list_items_recursive(category)
    if not items:
        cfg = load_clearance()
        items = list(cfg.get(category, {}).keys())
    return items

__all__ = [
    "BASE_DIR",
    "DOSSIERS_DIR",
    "CLEARANCE_FILE",
    "load_clearance",
    "save_clearance",
    "get_required_roles",
    "grant_file_clearance",
    "revoke_file_clearance",
    "set_category_clearance",
    "reset_category_clearance",
    "set_files_clearance",
    "list_categories",
    "list_items_recursive",
    "list_items",
    "create_dossier_file",
    "create_dossier_with_clearance",
    "remove_dossier_file",
    "update_dossier_raw",
    "patch_dossier_json_field",
    "has_access",
]
