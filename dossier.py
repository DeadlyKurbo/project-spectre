from __future__ import annotations

import datetime
import json
import os
from typing import Tuple, List, Set

from storage_spaces import (
    save_json, save_text, read_text, read_json,
    list_dir, delete_file, ensure_dir
)
from constants import ROOT_PREFIX, CATEGORY_ORDER, CATEGORY_STYLES, ARCHIVE_COLOR

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
    """Return dossier categories present in storage.

    The canonical list of categories lives in DigitalOcean Spaces and may not
    include every entry from :data:`constants.CATEGORY_ORDER`.  To avoid
    presenting "ghost" categories the function now inspects the storage
    backend and only returns directories that actually exist.  Configured
    slugs are preferred for matching categories so the UI preserves the
    intended ordering while remaining case-insensitive.  Any additional
    folders discovered on the backend are appended alphabetically.
    """

    configured = [slug for slug, _label in CATEGORY_ORDER]
    dirs, _files = _list_files_in(ROOT_PREFIX)

    # Map lower-case directory names to the actual folder names seen on the
    # backend to perform case-insensitive lookups and de-duplication.
    dir_map: dict[str, str] = {}
    for d in dirs:
        if not d.endswith("/"):
            continue
        name = d[:-1]
        low = name.lower()
        if name.startswith("_") or low == "acl" or low in dir_map:
            continue
        dir_map[low] = name

    result: List[str] = []
    for slug in configured:
        low = slug.lower()
        if low in dir_map:
            result.append(slug)
            dir_map.pop(low)

    # Append any remaining directories sorted alphabetically in a
    # case-insensitive manner so unexpected folders remain discoverable.
    result.extend(sorted(dir_map.values(), key=str.lower))
    return result


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


def list_archived_categories() -> List[str]:
    """Return archived dossier categories present in storage.

    Only categories that exist within the ``_archived`` prefix are returned.
    Configured slugs from :data:`constants.CATEGORY_ORDER` are used to
    determine ordering when matching existing directories in a
    case-insensitive manner.  Any additional folders found on the backend are
    appended alphabetically so they remain accessible.
    """

    configured = [slug for slug, _label in CATEGORY_ORDER]
    base = f"{ROOT_PREFIX}/_archived"
    dirs, _files = _list_files_in(base)

    dir_map: dict[str, str] = {}
    for d in dirs:
        if not d.endswith("/"):
            continue
        name = d[:-1]
        low = name.lower()
        if name.startswith("_") or low in dir_map:
            continue
        dir_map[low] = name

    result: List[str] = []
    for slug in configured:
        low = slug.lower()
        if low in dir_map:
            result.append(slug)
            dir_map.pop(low)

    result.extend(sorted(dir_map.values(), key=str.lower))
    return result


def list_archived_items_recursive(category: str, max_items: int = 3000) -> List[str]:
    """List archived items for a given category.

    ``category`` is matched case-insensitively so that folders such as
    ``Fleet`` and ``fleet`` are treated as the same logical category.
    Items from all matching folders are combined.
    """

    base = f"{ROOT_PREFIX}/_archived"
    dirs, _files = _list_files_in(base)
    matches = [d[:-1] for d in dirs if d.endswith("/") and d[:-1].lower() == category.lower()]
    items: set[str] = set()
    for real in matches:
        items.update(list_items_recursive(f"_archived/{real}", max_items))
        if len(items) >= max_items:
            break
    return sorted(items)


def delete_empty_archived_categories() -> list[str]:
    """Delete archived categories that contain no files.

    Returns a list of removed category names. Any errors during deletion are
    ignored so that a single failure doesn't abort the entire cleanup."""

    base = f"{ROOT_PREFIX}/_archived"
    dirs, _files = _list_files_in(base)
    removed: list[str] = []
    for d in dirs:
        if not d.endswith("/"):
            continue
        name = d[:-1]
        # Skip categories that still contain files
        if list_archived_items_recursive(name, max_items=1):
            continue
        # Remove the marker file if present
        try:
            delete_file(f"{base}/{name}/.keep")
        except Exception:
            pass
        # Attempt to remove the empty directory on local storage backends
        try:
            import utils
            os.rmdir(os.path.join(utils.DOSSIERS_DIR, "_archived", name))
        except Exception:
            pass
        removed.append(name)
    return sorted(removed, key=str.lower)


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


def archive_dossier_file(category: str, item_rel_base: str) -> str:
    found = _find_existing_item_key(category, item_rel_base)
    if not found:
        raise FileNotFoundError
    key, ext = found
    archived_key = key.replace(f"{ROOT_PREFIX}/", f"{ROOT_PREFIX}/_archived/", 1)
    ensure_dir(os.path.dirname(archived_key))
    if ext == ".json":
        data = read_json(key)
        save_json(archived_key, data)
    else:
        data = read_text(key)
        save_text(archived_key, data)
    delete_file(key)
    return archived_key


def restore_archived_file(category: str, item_rel_base: str) -> str:
    """Move an item from the archived area back to its original category.

    ``category`` is matched case-insensitively to avoid issues with folders
    whose casing differs from the user-provided slug.
    """

    base = f"{ROOT_PREFIX}/_archived"
    dirs, _files = _list_files_in(base)
    for d in dirs:
        if not d.endswith("/"):
            continue
        if d[:-1].lower() != category.lower():
            continue
        archived = f"_archived/{d[:-1]}"
        found = _find_existing_item_key(archived, item_rel_base)
        if not found:
            continue
        key, ext = found
        restored_key = key.replace(f"{ROOT_PREFIX}/_archived/", f"{ROOT_PREFIX}/", 1)
        ensure_dir(os.path.dirname(restored_key))
        if ext == ".json":
            data = read_json(key)
            save_json(restored_key, data)
        else:
            data = read_text(key)
            save_text(restored_key, data)
        delete_file(key)
        return restored_key

    raise FileNotFoundError


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


# ===== Category management =====

def create_category(
    slug: str,
    label: str,
    emoji: str | None = None,
    color: int | str | None = None,
) -> None:
    """Create a new dossier category and append it to ``CATEGORY_ORDER``.

    Parameters
    ----------
    slug:
        Identifier for the category.  Spaces are converted to underscores and
        the slug is stored in lowercase.
    label:
        Human readable label for UI elements.
    emoji:
        Optional emoji shown alongside the category.  Empty strings are
        treated as ``None``.
    color:
        Optional RGB colour for the category's button and menu.  Accepts an
        ``int`` or a hexadecimal string (e.g. ``"0xFF00AA"`` or ``"#FF00AA"``).
        When omitted, :data:`constants.ARCHIVE_COLOR` is used.

    The storage layer treats categories as directories under
    :data:`constants.ROOT_PREFIX`.  To expose a new category to the rest of the
    application we create the backing directory and update
    :data:`constants.CATEGORY_ORDER`.  The list is mutated in-place so modules
    that imported the object see the updated order immediately.  Styling
    information is stored in :data:`constants.CATEGORY_STYLES` so buttons and
    embeds pick up the configured emoji and colour.
    """

    slug = slug.strip().lower().replace(" ", "_")
    if any(existing == slug for existing, _label in CATEGORY_ORDER):
        raise ValueError(f"Category '{slug}' already exists")

    ensure_dir(_cat_prefix(slug))
    CATEGORY_ORDER.append((slug, label))

    # Normalise emoji: store ``None`` for blank strings to avoid empty emojis
    # in the UI which would otherwise trigger API errors.
    if isinstance(emoji, str):
        emoji = emoji.strip() or None

    # Coerce colour into an integer.  Accept a string so callers can provide
    # hex values.  Validate range to avoid invalid embed colours.
    if color is None:
        color_int = ARCHIVE_COLOR
    else:
        try:
            if isinstance(color, str):
                color_int = int(color.strip().lstrip("#"), 16)
            else:
                color_int = int(color)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise TypeError("color must be an integer RGB value") from exc
        if not (0 <= color_int <= 0xFFFFFF):
            raise ValueError("color must be between 0x000000 and 0xFFFFFF")

    CATEGORY_STYLES[slug] = (emoji, color_int)


def rename_category(old_slug: str, new_slug: str, new_label: str | None = None) -> None:
    """Rename an existing dossier category.

    Parameters
    ----------
    old_slug:
        Current category slug to rename.
    new_slug:
        New slug for the category.
    new_label:
        Optional new label for the category; if omitted the existing label is
        preserved.
    """

    old = old_slug.strip().lower().replace(" ", "_")
    new = new_slug.strip().lower().replace(" ", "_")
    if any(existing == new for existing, _label in CATEGORY_ORDER if existing != old):
        raise ValueError(f"Category '{new}' already exists")

    ensure_dir(_cat_prefix(new))

    for item in list_items_recursive(old):
        move_dossier_file(old, item, new)

    for item in list_archived_items_recursive(old):
        move_dossier_file(f"_archived/{old}", item, f"_archived/{new}")

    label = new_label
    for idx, (slug, lbl) in enumerate(CATEGORY_ORDER):
        if slug == old:
            label = label or lbl
            CATEGORY_ORDER[idx] = (new, label)
            break

    # Preserve styling for renamed categories so their emoji and color remain
    # associated with the new slug.  If the old category had no style defined
    # we still ensure the new slug has an entry to avoid KeyError lookups.
    emoji, color = CATEGORY_STYLES.pop(old, (None, ARCHIVE_COLOR))
    CATEGORY_STYLES[new] = (emoji, color)


def update_category_style(
    slug: str,
    emoji: str | None = None,
    color: int | str | None = None,
) -> None:
    """Update the emoji and/or colour for an existing dossier category.

    ``slug`` is normalised to match existing entries in
    :data:`constants.CATEGORY_ORDER`.  The ``emoji`` parameter may be provided
    as a string; empty values clear the emoji.  ``color`` accepts either an
    ``int`` or hexadecimal string and defaults to the category's current
    colour when omitted.
    """

    slug = slug.strip().lower().replace(" ", "_")
    if not any(existing == slug for existing, _label in CATEGORY_ORDER):
        raise ValueError(f"Category '{slug}' does not exist")

    current_emoji, current_color = CATEGORY_STYLES.get(slug, (None, ARCHIVE_COLOR))

    if isinstance(emoji, str):
        emoji = emoji.strip() or None
    elif emoji is None:
        emoji = current_emoji

    if color is None:
        color_int = current_color
    else:
        try:
            if isinstance(color, str):
                color_int = int(color.strip().lstrip("#"), 16)
            else:
                color_int = int(color)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise TypeError("color must be an integer RGB value") from exc
        if not (0 <= color_int <= 0xFFFFFF):
            raise ValueError("color must be between 0x000000 and 0xFFFFFF")

    CATEGORY_STYLES[slug] = (emoji, color_int)

def reorder_categories(order: list[str]) -> None:
    """Reorder existing categories based on ``order``.

    ``order`` is a list of category slugs in their desired sequence.  Any
    slugs not present in :data:`CATEGORY_ORDER` are ignored.  Categories not
    referenced in ``order`` retain their original relative ordering and are
    appended at the end of the list.
    """

    slug_to_label = {slug: label for slug, label in CATEGORY_ORDER}

    # Build the new order while ignoring unknown or duplicate slugs.
    seen: Set[str] = set()
    new_order = []
    for slug in order:
        if slug in slug_to_label and slug not in seen:
            new_order.append((slug, slug_to_label[slug]))
            seen.add(slug)

    # Append any remaining categories that weren't explicitly ordered.
    remaining = [item for item in CATEGORY_ORDER if item[0] not in seen]
    new_order.extend(remaining)

    CATEGORY_ORDER[:] = new_order


# ===== File management =====

def move_dossier_file(
    src_category: str,
    item_rel_base: str,
    dest_category: str,
    new_item_rel_base: str | None = None,
) -> str:
    """Move or rename a dossier file.

    Parameters
    ----------
    src_category:
        Original category of the file.
    item_rel_base:
        Original item name without extension.
    dest_category:
        Target category for the file.
    new_item_rel_base:
        Optional new item name (without extension).  If omitted the original
        name is retained.

    Returns
    -------
    str
        The storage key of the moved file.
    """

    found = _find_existing_item_key(src_category, item_rel_base)
    if not found:
        raise FileNotFoundError
    key, ext = found

    new_base = new_item_rel_base or item_rel_base
    if _find_existing_item_key(dest_category, new_base):
        raise FileExistsError
    subdir, fname = _split_dir_file(new_base)
    dir_prefix = f"{_cat_prefix(dest_category)}/{subdir}".strip("/").replace("//", "/")
    ensure_dir(dir_prefix)
    new_key = f"{dir_prefix}/{fname}{ext}".replace("//", "/")

    if ext == ".json":
        data = read_json(key)
        save_json(new_key, data)
    else:
        data = read_text(key)
        save_text(new_key, data)
    delete_file(key)
    return new_key


def rename_dossier_file(category: str, item_rel_base: str, new_item_rel_base: str) -> str:
    """Rename a file within the same category."""

    return move_dossier_file(category, item_rel_base, category, new_item_rel_base)
