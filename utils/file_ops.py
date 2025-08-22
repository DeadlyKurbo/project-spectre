import os, json, datetime
from storage_spaces import (
    save_json, save_text, read_text, read_json,
    list_dir, delete_file, ensure_dir
)
from config import ROOT_PREFIX, ROLE_LEVELS

SYSTEM_DIRS = {"acl", "_backups"}  # verbergen in UI
SYSTEM_SEGMENTS = {"/_versions/", "/_backups/"}  # verbergen in UI

def ts() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

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

# ========= ACL (stored in Spaces) =========
ACL_KEY = f"{ROOT_PREFIX}/acl/clearance.json".replace("//", "/")

def load_clearance() -> dict:
    try:
        return read_json(ACL_KEY)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}

def save_clearance(cfg: dict) -> None:
    ensure_dir(f"{ROOT_PREFIX}/acl")
    save_json(ACL_KEY, cfg)

def get_required_roles(category: str, item_rel_base: str) -> set[int]:
    cf = load_clearance()
    roles = cf.get(category, {}).get(item_rel_base, [])
    return set(int(r) for r in roles)

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

# ========= Listing / IO =========
def list_categories() -> list[str]:
    dirs, _files = _list_files_in(ROOT_PREFIX)
    cats = []
    for d in dirs:
        if not d.endswith("/"):
            continue
        name = d[:-1]
        if name.startswith("_"):
            continue
        if name in SYSTEM_DIRS:
            continue
        cats.append(name)
    if not cats:
        cats = ["missions", "personnel", "intelligence"]
    return sorted(set(cats))

def list_items_recursive(category: str, max_items: int = 3000) -> list[str]:
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
        # files
        for name, _size in files:
            full = f"{base}/{name}".replace("//", "/")
            skip = False
            if any(seg in full for seg in SYSTEM_SEGMENTS):
                skip = True
            if "/acl/" in full:
                skip = True
            if skip:
                continue
            if name.lower().endswith((".json", ".txt")):
                rel_from_cat = full[len(root):].strip("/").replace("\\", "/")
                items_base.add(_strip_ext(rel_from_cat))
        # dirs
        for d in dirs:
            dname = d.strip("/")
            if dname.startswith("_") or dname in SYSTEM_DIRS or dname == "acl":
                continue
            stack.append(f"{base}/{dname}".replace("//", "/"))
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
    found = _find_existing_item_key(category, item_rel_base)
    if not found:
        raise FileNotFoundError
    key, ext = found
    # bewaar één versie vóór overschrijven
    try:
        save_version(key)
    except Exception:
        pass
    if ext == ".json":
        try:
            data = json.loads(new_content)
        except Exception as e:
            raise ValueError(f"Invalid JSON: {e}")
        save_json(key, data)
    else:
        try:
            data = json.loads(new_content)
            save_text(key, json.dumps(data, ensure_ascii=False, indent=2))
        except Exception:
            save_text(key, new_content)
    return key

def _set_by_path(obj: dict, path: str, value):
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
    found = _find_existing_item_key(category, item_rel_base)
    if not found:
        raise FileNotFoundError
    key, ext = found
    try:
        data = read_json(key)
    except Exception:
        blob = read_text(key)
        data = json.loads(blob)
    if not isinstance(data, dict):
        raise ValueError("Root must be a JSON object to patch a field.")
    try:
        new_val = json.loads(value_text)
    except Exception:
        new_val = value_text
    _set_by_path(data, field_path, new_val)
    if ext == ".json":
        save_json(key, data)
    else:
        save_text(key, json.dumps(data, ensure_ascii=False, indent=2))
    return key

def _version_path(key: str) -> str:
    base_dir, fname = key.rsplit("/", 1)
    ver_dir = f"{base_dir}/_versions".replace("//", "/")
    ensure_dir(ver_dir)
    tstamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ver_dir}/{tstamp}-{fname}"

def save_version(key: str):
    try:
        try:
            data = read_json(key)
            blob = json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            blob = read_text(key)
        ver_key = _version_path(key)
        save_text(ver_key, blob)
    except Exception:
        pass

def _user_level(user_roles: set[int]) -> int:
    lvl = 0
    for rid in user_roles:
        lvl = max(lvl, int(ROLE_LEVELS.get(rid, 0)))
    return lvl

def has_access(category: str, item_rel_base: str, user_roles: set[int], owner_admin: bool) -> tuple[bool, set[int]]:
    required = get_required_roles(category, item_rel_base)
    if required:
        if owner_admin or (user_roles & required):
            return True, required
        return False, required
    # Fallback: dynamic by JSON field "clearance": N
    try:
        found = _find_existing_item_key(category, item_rel_base)
        if not found:
            return False, set()
        key, _ = found
        data = read_json(key)
        level_needed = int(data.get("clearance", 0))
    except Exception:
        level_needed = 0
    user_lvl = _user_level(user_roles)
    return (owner_admin or user_lvl >= level_needed), set()
