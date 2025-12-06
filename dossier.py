from __future__ import annotations

import datetime
import json
import os
import re
from typing import Tuple, List, Set, Optional

from storage_spaces import (
    save_json,
    save_text,
    read_text,
    read_json,
    list_dir,
    delete_file,
    ensure_dir,
)
from constants import (
    ROOT_PREFIX,
    CATEGORY_ORDER,
    CATEGORY_STYLES,
    ARCHIVE_COLOR,
    PAGE_SEPARATOR,
    save_category_manifest,
)
from server_config import get_server_config

# ======== Helpers =========

def ts() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _normalize_category(name: str) -> str:
    """Return a normalised identifier for ``name``.

    Any run of non-alphanumeric characters (including spaces, hyphens and
    punctuation) is collapsed into a single underscore so that directory names
    like ``"Tech & Equipment"`` correctly map to the configured slug
    ``"tech_equipment"``.  Leading and trailing underscores are stripped to
    ensure consistent matching.
    """

    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _root_prefix(guild_id: Optional[int] = None) -> str:
    if guild_id:
        cfg = get_server_config(guild_id)
        root_pref = None
        if hasattr(cfg, "get"):
            try:
                root_pref = cfg.get("ROOT_PREFIX")
            except Exception:
                root_pref = None
        elif isinstance(cfg, dict):
            root_pref = cfg.get("ROOT_PREFIX")
        if isinstance(root_pref, str):
            cleaned = root_pref.strip().strip("/")
            if cleaned:
                return cleaned
        # Fallback segregates by guild to avoid cross-contamination
        return f"{ROOT_PREFIX}/{guild_id}"
    return ROOT_PREFIX


def _archive_root_prefixes(guild_id: Optional[int] = None) -> list[str]:
    roots: list[str] = []

    def _append(root_value: Optional[str]) -> None:
        if root_value is None:
            return
        value = str(root_value).strip()
        candidate = value.strip("/") if value else ""
        if candidate not in roots:
            roots.append(candidate)

    base = _root_prefix(guild_id)
    _append(base)

    if guild_id:
        cfg = get_server_config(guild_id)
        archive_cfg = None
        if hasattr(cfg, "get"):
            try:
                archive_cfg = cfg.get("archive")
            except Exception:
                archive_cfg = None
        elif isinstance(cfg, dict):
            archive_cfg = cfg.get("archive")
        if isinstance(archive_cfg, dict):
            links = archive_cfg.get("links")
            if isinstance(links, list):
                for entry in links:
                    if not isinstance(entry, dict):
                        continue
                    root_value = entry.get("root_prefix")
                    if isinstance(root_value, str):
                        _append(root_value)

    if not roots:
        _append(ROOT_PREFIX)
    return roots or [""]


def _category_locations(category: str, guild_id: Optional[int] = None) -> list[tuple[str, bool, str]]:
    cat = category.strip().strip("/")
    archived = False
    if cat.startswith("_archived/"):
        archived = True
        cat = cat.split("/", 1)[1] if "/" in cat else ""

    matches: list[tuple[str, bool, str]] = []
    target = _normalize_category(cat)
    for root in _archive_root_prefixes(guild_id):
        base = f"{root}/_archived" if archived else root
        base = base.strip("/")
        dirs, _files = _list_files_in(base)
        for d in dirs:
            if not d.endswith("/"):
                continue
            name = d[:-1]
            if _normalize_category(name) == target:
                matches.append((root, archived, name))
                break

    if not matches:
        fallback_root = _archive_root_prefixes(guild_id)[0]
        matches.append((fallback_root, archived, cat))
    return matches


def _root_for_key(key: str, guild_id: Optional[int] = None) -> str:
    clean = key.strip().lstrip("/")
    for root in _archive_root_prefixes(guild_id):
        if root:
            prefix = f"{root}/"
            archived_prefix = f"{root}/_archived/"
            if clean.startswith(prefix) or clean.startswith(archived_prefix):
                return root
        else:
            return ""
    return _archive_root_prefixes(guild_id)[0]


def _join_storage_path(*segments: str) -> str:
    cleaned = [str(seg).strip("/") for seg in segments if seg not in (None, "")]
    return "/".join(cleaned).strip("/")


def _strip_root_segment(key: str, root: str, *, archived: bool = False) -> str:
    if root:
        prefix = f"{root}/_archived/" if archived else f"{root}/"
        if key.startswith(prefix):
            return key[len(prefix) :]
    else:
        if archived and key.startswith("_archived/"):
            return key[len("_archived/") :]
    return key


def ensure_guild_archive_structure(guild_id: int, root_prefix: Optional[str] = None) -> str:
    """Ensure the archive directories for ``guild_id`` exist."""

    prefix = (root_prefix or _root_prefix(guild_id)).strip().strip("/")
    if not prefix:
        raise ValueError("root_prefix cannot be empty")
    ensure_dir(prefix)
    ensure_dir(f"{prefix}/_archived")
    return prefix


def _resolve_category_dir(category: str, archived: bool = False, guild_id: Optional[int] = None) -> str:
    locations = _category_locations(
        f"_archived/{category}" if archived else category,
        guild_id=guild_id,
    )
    # The helper always returns at least one entry.
    return locations[0][2]


def _cat_prefix(category: str, guild_id: Optional[int] = None) -> str:
    """Return the storage prefix for ``category``.

    The function accepts both configured slugs (e.g. ``"tech_equipment"``) and
    literal directory names.  When a slug is provided it is resolved to the
    actual on-disk directory to ensure that operations such as archiving files
    work even if the stored folder uses spaces or different casing.
    """

    cat = category.strip().strip("/")
    if cat.startswith("_archived/"):
        locations = _category_locations(cat, guild_id=guild_id)
    else:
        locations = _category_locations(cat, guild_id=guild_id)
    root, archived, resolved = locations[0]
    base = f"{root}/_archived" if archived else root
    return f"{base}/{resolved}".replace("//", "/").strip("/")


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
    except Exception as e:
        import logging; logging.getLogger("spectre").warning("list_dir failed for %r: %s", path_prefix, e)
        return [], []


def _find_existing_item_key(category: str, item_rel_base: str, guild_id: Optional[int] = None):
    """Directory-based existence check; returns (key, ext) or None."""
    base_rel = item_rel_base.strip().strip("/")
    subdir, fname = _split_dir_file(base_rel)
    for root, archived, resolved in _category_locations(category, guild_id=guild_id):
        base = f"{root}/_archived/{resolved}" if archived else f"{root}/{resolved}"
        dir_prefix = f"{base}/{subdir}".strip("/").replace("//", "/")
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


def describe_dossier_key(key: str, guild_id: Optional[int] = None) -> dict[str, object]:
    """Return metadata describing a stored dossier key.

    The returned mapping includes ``category`` (without archive prefix), the
    ``item`` name without an extension, the ``ext`` of the stored file, and
    whether the entry lives inside the archived tree.
    """

    clean = key.strip().lstrip("/")
    root = _root_for_key(clean, guild_id)
    archived = False

    if clean.startswith(f"{root}/_archived/") or (not root and clean.startswith("_archived/")):
        archived = True
        relative = _strip_root_segment(clean, root, archived=True)
    else:
        relative = _strip_root_segment(clean, root, archived=False)

    parts = relative.split("/", 1)
    if len(parts) != 2:
        raise ValueError("Unable to resolve dossier key components")

    category, remainder = parts
    remainder = remainder.strip()
    ext = ""
    if "." in remainder:
        ext = "." + remainder.rsplit(".", 1)[-1]
    return {
        "key": clean,
        "root": root,
        "relative": relative,
        "category": category,
        "item": _strip_ext(remainder),
        "ext": ext,
        "archived": archived,
    }

# ========= Listing / IO =========


def list_categories(guild_id: Optional[int] = None) -> List[str]:
    """Return dossier categories ensuring the canonical set is always present.

    The canonical category manifest is stored in DigitalOcean Spaces so every
    guild sees the same menu structure.  Additional directories that exist in
    storage but are not part of the manifest are appended alphabetically so
    legacy folders remain discoverable.
    """

    configured = [slug for slug, _label in CATEGORY_ORDER]

    dir_map: dict[str, str] = {}
    for root in _archive_root_prefixes(guild_id):
        dirs, _files = _list_files_in(root)
        for d in dirs:
            if not d.endswith("/"):
                continue
            name = d[:-1]
            low = _normalize_category(name)
            if (
                name.startswith("_")
                or low == "acl"
                or low in dir_map
            ):
                continue
            dir_map[low] = name

    result: List[str] = []
    for slug in configured:
        if slug not in result:
            result.append(slug)
        low = _normalize_category(slug)
        if low:
            dir_map.pop(low, None)

    for name in sorted(dir_map.values(), key=str.lower):
        result.append(name)
    return result


def list_items_recursive(category: str, max_items: int = 3000, guild_id: Optional[int] = None) -> List[str]:
    items_base: set[str] = set()
    for root, archived, resolved in _category_locations(category, guild_id=guild_id):
        if len(items_base) >= max_items:
            break
        base_root = f"{root}/_archived/{resolved}" if archived else f"{root}/{resolved}"
        base_root = base_root.replace("//", "/").strip("/")
        stack = [base_root]
        seen = set()
        while stack and len(items_base) < max_items:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            dirs, files = _list_files_in(current)
            for name, _size in files:
                if name.lower().endswith((".json", ".txt")):
                    rel = f"{current}/{name}".replace("//", "/")
                    rel_from_cat = rel[len(base_root):].strip("/").replace("\\", "/")
                    items_base.add(_strip_ext(rel_from_cat))
            for d in dirs:
                stack.append(f"{current}/{d.strip('/')}".replace("//", "/"))
    return sorted(items_base)


def _describe_category_files(category: str, *, archived: bool, guild_id: Optional[int] = None) -> list[dict[str, object]]:
    target = f"_archived/{category}" if archived else category
    descriptors: list[dict[str, object]] = []
    for item in list_items_recursive(target, max_items=5000, guild_id=guild_id):
        found = _find_existing_item_key(target, item, guild_id=guild_id)
        if not found:
            continue
        key, ext = found
        try:
            meta = describe_dossier_key(key, guild_id=guild_id)
        except Exception:
            continue
        meta.update(
            {
                "category": category,
                "name": item,
                "ext": ext,
                "archived": archived,
            }
        )
        descriptors.append(meta)
    return descriptors


def enumerate_dossier_files(guild_id: Optional[int] = None) -> list[dict[str, object]]:
    """Return descriptors for every dossier file, including archived items."""

    descriptors: list[dict[str, object]] = []
    for category in list_categories(guild_id=guild_id):
        descriptors.extend(_describe_category_files(category, archived=False, guild_id=guild_id))
    for category in list_archived_categories(guild_id=guild_id):
        descriptors.extend(_describe_category_files(category, archived=True, guild_id=guild_id))

    return sorted(
        descriptors,
        key=lambda item: (str(item.get("archived")), str(item.get("category")), str(item.get("name"))),
    )


def list_archived_categories(guild_id: Optional[int] = None) -> List[str]:
    """Return archived dossier categories present in storage.

    Only categories that exist within the ``_archived`` prefix are returned.
    Configured slugs from :data:`constants.CATEGORY_ORDER` are used to
    determine ordering when matching existing directories in a
    case-insensitive manner.  Any additional folders found on the backend are
    appended alphabetically so they remain accessible.
    """

    configured = [slug for slug, _label in CATEGORY_ORDER]

    dir_map: dict[str, str] = {}
    for root in _archive_root_prefixes(guild_id):
        base = f"{root}/_archived".strip("/")
        dirs, _files = _list_files_in(base)
        for d in dirs:
            if not d.endswith("/"):
                continue
            name = d[:-1]
            low = _normalize_category(name)
            if name.startswith("_") or low in dir_map:
                continue
            dir_map[low] = name

    result: List[str] = []
    for slug in configured:
        low = _normalize_category(slug)
        if low in dir_map:
            result.append(slug)
            dir_map.pop(low)

    result.extend(sorted(dir_map.values(), key=str.lower))
    return result


def list_archived_items_recursive(category: str, max_items: int = 3000, guild_id: Optional[int] = None) -> List[str]:
    """List archived items for a given category.

    ``category`` is matched case-insensitively so that folders such as
    ``Fleet`` and ``fleet`` are treated as the same logical category.
    Items from all matching folders are combined.
    """

    norm = _normalize_category
    items: set[str] = set()
    target = norm(category)
    for root in _archive_root_prefixes(guild_id):
        base = f"{root}/_archived".strip("/")
        dirs, _files = _list_files_in(base)
        matches = [d[:-1] for d in dirs if d.endswith("/") and norm(d[:-1]) == target]
        for real in matches:
            items.update(list_items_recursive(f"_archived/{real}", max_items, guild_id=guild_id))
            if len(items) >= max_items:
                return sorted(items)
    return sorted(items)


def delete_empty_archived_categories(guild_id: Optional[int] = None) -> list[str]:
    """Delete archived categories that contain no files.

    Returns a list of removed category names. Any errors during deletion are
    ignored so that a single failure doesn't abort the entire cleanup."""

    base = f"{_root_prefix(guild_id)}/_archived"
    dirs, _files = _list_files_in(base)
    removed: list[str] = []
    for d in dirs:
        if not d.endswith("/"):
            continue
        name = d[:-1]
        # Skip categories that still contain files
        if list_archived_items_recursive(name, max_items=1, guild_id=guild_id):
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


def create_dossier_file(category: str, item_rel_input: str, content: str, prefer_txt_default: bool = True, guild_id: Optional[int] = None) -> str:
    item_rel_input = item_rel_input.strip().strip("/")
    has_ext = item_rel_input.lower().endswith((".json", ".txt"))
    if not has_ext:
        item_base = item_rel_input
        target_name = item_base + (".txt" if prefer_txt_default else ".json")
    else:
        item_base    = _strip_ext(item_rel_input)
        target_name  = item_rel_input
    if _find_existing_item_key(category, item_base, guild_id=guild_id):
        raise FileExistsError
    subdir, _fname = _split_dir_file(item_base)
    dir_prefix = f"{_cat_prefix(category, guild_id=guild_id)}/{subdir}".strip("/").replace("//", "/")
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


def remove_dossier_file(category: str, item_rel_base: str, guild_id: Optional[int] = None) -> None:
    found = _find_existing_item_key(category, item_rel_base, guild_id=guild_id)
    if not found:
        raise FileNotFoundError
    key, _ = found
    delete_file(key)


def read_dossier_body(key: str, guild_id: Optional[int] = None) -> tuple[str, str]:
    """Return the raw text body for a dossier file along with its extension."""

    descriptor = describe_dossier_key(key, guild_id=guild_id)
    ext = str(descriptor.get("ext") or "").lower()
    if ext == ".json":
        data = read_json(key)
        return json.dumps(data, ensure_ascii=False, indent=2), ext
    return read_text(key), ext


def archive_dossier_file(category: str, item_rel_base: str, guild_id: Optional[int] = None) -> str:
    found = _find_existing_item_key(category, item_rel_base, guild_id=guild_id)
    if not found:
        raise FileNotFoundError
    key, ext = found
    root = _root_for_key(key, guild_id)
    relative = _strip_root_segment(key, root, archived=False)
    archived_key = _join_storage_path(root, "_archived", relative)
    dir_name = os.path.dirname(archived_key)
    if dir_name:
        ensure_dir(dir_name)
    if ext == ".json":
        data = read_json(key)
        save_json(archived_key, data)
    else:
        data = read_text(key)
        save_text(archived_key, data)
    delete_file(key)
    return archived_key


def restore_archived_file(category: str, item_rel_base: str, guild_id: Optional[int] = None) -> str:
    """Move an item from the archived area back to its original category.

    ``category`` is matched case-insensitively to avoid issues with folders
    whose casing differs from the user-provided slug.
    """

    archived_category = f"_archived/{category}"
    found = _find_existing_item_key(archived_category, item_rel_base, guild_id=guild_id)
    if not found:
        raise FileNotFoundError

    key, ext = found
    root = _root_for_key(key, guild_id)
    relative = _strip_root_segment(key, root, archived=True)
    restored_key = _join_storage_path(root, relative)
    dir_name = os.path.dirname(restored_key)
    if dir_name:
        ensure_dir(dir_name)
    if ext == ".json":
        data = read_json(key)
        save_json(restored_key, data)
    else:
        data = read_text(key)
        save_text(restored_key, data)
    delete_file(key)
    return restored_key


def update_dossier_raw(category: str, item_rel_base: str, new_content: str, guild_id: Optional[int] = None) -> str:
    """Overwrite file with provided raw content. Tries to keep JSON as JSON."""
    found = _find_existing_item_key(category, item_rel_base, guild_id=guild_id)
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


def patch_dossier_json_field(category: str, item_rel_base: str, field_path: str, value_text: str, guild_id: Optional[int] = None) -> str:
    """Patch a single JSON field. Parses value as JSON if possible, else string."""
    found = _find_existing_item_key(category, item_rel_base, guild_id=guild_id)
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


def attach_dossier_image(
    category: str,
    item_rel_base: str,
    page: int,
    image_url: str,
    guild_id: Optional[int] = None,
) -> str:
    """Append an image URL to the bottom of a page in a text dossier.

    Parameters
    ----------
    category:
        Dossier category containing the file.
    item_rel_base:
        Base name of the dossier item (without extension) or path relative to
        the category.
    page:
        1-based index of the page to which the image should be attached.
    image_url:
        Direct link to the image.

    Returns
    -------
    str
        Storage key of the updated dossier file.
    """

    found = _find_existing_item_key(category, item_rel_base, guild_id=guild_id)
    if not found:
        raise FileNotFoundError
    key, _ext = found
    blob = read_text(key)
    pages = blob.split(PAGE_SEPARATOR) if PAGE_SEPARATOR in blob else [blob]
    if page < 1 or page > len(pages):
        raise IndexError("Invalid page index")
    idx = page - 1
    segment = pages[idx]
    if segment and not segment.endswith("\n"):
        segment += "\n"
    segment += f"[IMAGE]: {image_url}\n"
    pages[idx] = segment
    save_text(key, PAGE_SEPARATOR.join(pages))
    return key


# ===== Category management =====

def create_category(
    slug: str,
    label: str,
    emoji: str | None = None,
    color: int | str | None = None,
    guild_id: Optional[int] = None,
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
    for idx, (existing, _label) in enumerate(CATEGORY_ORDER):
        if existing == slug:
            CATEGORY_ORDER[idx] = (slug, label)
            break
    else:
        CATEGORY_ORDER.append((slug, label))

    ensure_dir(_cat_prefix(slug, guild_id=guild_id))

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
    save_category_manifest()


def rename_category(old_slug: str, new_slug: str, new_label: str | None = None, guild_id: Optional[int] = None) -> None:
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

    ensure_dir(_cat_prefix(new, guild_id=guild_id))

    for item in list_items_recursive(old, guild_id=guild_id):
        move_dossier_file(old, item, new, guild_id=guild_id)

    for item in list_archived_items_recursive(old, guild_id=guild_id):
        move_dossier_file(f"_archived/{old}", item, f"_archived/{new}", guild_id=guild_id)

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
    save_category_manifest()


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
    save_category_manifest()

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
    save_category_manifest()


# ===== File management =====

def move_dossier_file(
    src_category: str,
    item_rel_base: str,
    dest_category: str,
    new_item_rel_base: str | None = None,
    guild_id: Optional[int] = None,
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

    found = _find_existing_item_key(src_category, item_rel_base, guild_id=guild_id)
    if not found:
        raise FileNotFoundError
    key, ext = found

    new_base = new_item_rel_base or item_rel_base
    if _find_existing_item_key(dest_category, new_base, guild_id=guild_id):
        raise FileExistsError
    subdir, fname = _split_dir_file(new_base)
    dir_prefix = f"{_cat_prefix(dest_category, guild_id=guild_id)}/{subdir}".strip("/").replace("//", "/")
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


def rename_dossier_file(category: str, item_rel_base: str, new_item_rel_base: str, guild_id: Optional[int] = None) -> str:
    """Rename a file within the same category."""

    return move_dossier_file(category, item_rel_base, category, new_item_rel_base, guild_id=guild_id)
