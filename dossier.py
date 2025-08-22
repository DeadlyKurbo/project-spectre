from __future__ import annotations

import datetime
import json
from typing import Tuple, List, Set

from storage_spaces import (
    save_json, save_text, read_text, read_json,
    list_dir, delete_file, ensure_dir
)
from constants import ROOT_PREFIX

# ======== Helpers =========

def ts() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _cat_prefix(category: str) -> str:
    return f"{ROOT_PREFIX}/{category}".replace("//", "/").strip("/")


def _strip_ext(name: str) -> str:
    low = name.lower()
    for ext in (".json", ".txt"):
        if low.endswith(ext):
            return name[: -len(ext)]
    return name


def _split_dir_file(rel: str):
    rel = rel.strip().strip("/")
    if "/" in rel:
        d, f = rel.rsplit("/", 1)
        return d, f
    return "", rel


def _list_files_in(path_prefix: str):
    try:
        return list_dir(path_prefix)
    except FileNotFoundError:
        return [], []
    except Exception:
        return [], []


def _find_existing_item_key(category: str, item_rel_base: str):
    """Directory-based existence check; returns (key, ext) or None."""
    base_rel = item_rel_base.strip().strip("/")
    subdir, fname = _split_dir_file(base_rel)
    dir_prefix = f"{_cat_prefix(category)}/{subdir}".strip("/").replace("//", "/")
    _dirs, files = _list_files_in(dir_prefix)
    candidates = [f"{fname}.json", f"{fname}.txt", fname]
    file_names = {n.lower(): n for (n, _sz) in files}
    for cand in candidates:
        low = cand.lower()
        if low in file_names:
            real = file_names[low]
            key = f"{dir_prefix}/{real}".replace("//", "/")
            ext = ".json" if real.lower().endswith(".json") else ".txt" if real.lower().endswith(".txt") else ""
            return key, (ext or ".txt")
    return None

# ========= Listing / IO =========

def list_categories() -> List[str]:
    dirs, _files = _list_files_in(ROOT_PREFIX)
    cats = [d[:-1] for d in dirs if d.endswith("/")]
    if not cats:
        cats = ["missions", "personnel", "intelligence"]
    cats = [c for c in cats if c.lower() != "acl"]
    if not cats:
        cats = ["missions", "personnel", "intelligence"]
    return sorted(set(cats))


def list_items_recursive(category: str, max_items: int = 3000) -> List[str]:
    root = _cat_prefix(category)
    items_base = set()
    stack = [root]
    seen = set()
    while stack and len(items_base) < max_items:
        base = stack.pop()
        if base in seen:
            continue
        seen.add(base)
        dirs, files = _list_files_in(base)
        for name, _size in files:
            if name.lower().endswith((".json", ".txt")):
                rel = f"{base}/{name}".replace("//", "/")
                rel_from_cat = rel[len(root):].strip("/").replace("\\", "/")
                items_base.add(_strip_ext(rel_from_cat))
        for d in dirs:
            stack.append(f"{base}/{d.strip('/')}".replace("//", "/"))
    return sorted(items_base)


def create_dossier_file(category: str, item_rel_input: str, content: str, prefer_txt_default: bool = True) -> str:
    item_rel_input = item_rel_input.strip().strip("/")
    has_ext = item_rel_input.lower().endswith((".json", ".txt"))
    if not has_ext:
        item_base = item_rel_input
        target_name = item_base + (".txt" if prefer_txt_default else ".json")
    else:
        item_base    = _strip_ext(item_rel_input)
        target_name  = item_rel_input
    if _find_existing_item_key(category, item_base):
        raise FileExistsError
    subdir, _fname = _split_dir_file(item_base)
    dir_prefix = f"{_cat_prefix(category)}/{subdir}".strip("/").replace("//", "/")
    ensure_dir(dir_prefix)
    key = f"{dir_prefix}/{target_name}".replace("//", "/")
    try:
        data = json.loads(content)
        if key.lower().endswith(".json"):
            save_json(key, data)
        else:
            save_text(key, json.dumps(data, ensure_ascii=False, indent=2))
    except Exception:
        if not key.lower().endswith((".json", ".txt")):
            key += ".txt"
        save_text(key, content)
    return key


def remove_dossier_file(category: str, item_rel_base: str) -> None:
    found = _find_existing_item_key(category, item_rel_base)
    if not found:
        raise FileNotFoundError
    key, _ = found
    delete_file(key)


def update_dossier_raw(category: str, item_rel_base: str, new_content: str) -> str:
    """Overwrite file with provided raw content. Tries to keep JSON as JSON."""
    found = _find_existing_item_key(category, item_rel_base)
    if not found:
        raise FileNotFoundError
    key, ext = found
    if ext == ".json":
        try:
            data = json.loads(new_content)
        except Exception as e:
            raise ValueError(f"Invalid JSON: {e}")
        save_json(key, data)
    else:
        # allow JSON in .txt as pretty text, else plain text
        try:
            data = json.loads(new_content)
            save_text(key, json.dumps(data, ensure_ascii=False, indent=2))
        except Exception:
            save_text(key, new_content)
    return key


def _set_by_path(obj: dict, path: str, value):
    """Set nested key by dot.path (creates intermediate dicts)."""
    parts = [p for p in path.split(".") if p]
    if not parts:
        raise ValueError("Empty field path")
    cur = obj
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def patch_dossier_json_field(category: str, item_rel_base: str, field_path: str, value_text: str) -> str:
    """Patch a single JSON field. Parses value as JSON if possible, else string."""
    found = _find_existing_item_key(category, item_rel_base)
    if not found:
        raise FileNotFoundError
    key, ext = found
    # Read JSON (if txt, attempt to parse)
    try:
        data = read_json(key)
    except Exception:
        # try from text
        blob = read_text(key)
        data = json.loads(blob)
    if not isinstance(data, dict):
        raise ValueError("Root must be a JSON object to patch a field.")
    # Parse value
    try:
        new_val = json.loads(value_text)
    except Exception:
        new_val = value_text  # treat as string
    _set_by_path(data, field_path, new_val)
    # Save back following original ext
    if ext == ".json":
        save_json(key, data)
    else:
        save_text(key, json.dumps(data, ensure_ascii=False, indent=2))
    return key
