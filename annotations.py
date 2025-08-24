from __future__ import annotations

from datetime import datetime, UTC
import re

from storage_spaces import read_text, save_text, ensure_dir


def _annotation_path(category: str, item_rel_base: str) -> str:
    cat = category.strip().strip("/")
    item = item_rel_base.strip().strip("/")
    return f"logs/annotations/{cat}/{item}.log"


def add_file_annotation(
    category: str, item_rel_base: str, author: int | str, note: str
) -> str:
    """Append a note about a file to its annotation log.

    The author may be provided as a numeric Discord ID, mention string or
    display name. Numeric IDs and mentions will result in an actual ping when
    viewed in Discord.

    Returns the storage path of the log file."""
    key = _annotation_path(category, item_rel_base)
    ensure_dir("/".join(key.split("/")[:-1]))
    try:
        existing = read_text(key)
    except Exception:
        existing = ""
    ts = datetime.now(UTC).strftime("%Y-%m-%d")
    if isinstance(author, int) or (isinstance(author, str) and author.isdigit()):
        author_disp = f"<@{int(author)}>"
    else:
        author = str(author)
        if author.startswith("<@") or author.startswith("@"):
            author_disp = author
        else:
            author_disp = f"@{author}"
    entry = f"[{ts}] {author_disp}: {note}"
    save_text(key, existing + entry + "\n")
    return key


def _read_annotation_lines(key: str) -> list[str]:
    try:
        content = read_text(key)
    except Exception:
        return []
    return [line for line in content.splitlines() if line.strip()]


def update_file_annotation(
    category: str,
    item_rel_base: str,
    index: int,
    new_note: str,
    author_id: int | None = None,
) -> str:
    """Update an existing annotation entry.

    If ``author_id`` is provided, the operation will only succeed if the
    annotation was originally created by that author.
    Returns the storage path of the log file."""
    key = _annotation_path(category, item_rel_base)
    lines = _read_annotation_lines(key)
    if index < 0 or index >= len(lines):
        raise IndexError("annotation index out of range")
    if author_id is not None:
        match = re.search(r"<@(\d+)>", lines[index])
        if not match or int(match.group(1)) != int(author_id):
            raise PermissionError("cannot edit others' annotations")
    ts_match = re.match(r"^\[(.+?)\]", lines[index])
    ts = ts_match.group(1) if ts_match else datetime.now(UTC).strftime("%Y-%m-%d")
    author_match = re.search(r"<@\d+>|@[^:]+", lines[index])
    if author_match:
        author_disp = author_match.group(0)
    elif author_id is not None:
        author_disp = f"<@{author_id}>"
    else:
        author_disp = "@unknown"
    lines[index] = f"[{ts}] {author_disp}: {new_note}"
    save_text(key, "\n".join(lines) + "\n")
    return key


def remove_file_annotation(
    category: str,
    item_rel_base: str,
    index: int,
    author_id: int | None = None,
) -> str:
    """Remove an annotation entry.

    If ``author_id`` is provided, removal is only allowed for entries created
    by that author.
    Returns the storage path of the log file."""
    key = _annotation_path(category, item_rel_base)
    lines = _read_annotation_lines(key)
    if index < 0 or index >= len(lines):
        raise IndexError("annotation index out of range")
    if author_id is not None:
        match = re.search(r"<@(\d+)>", lines[index])
        if not match or int(match.group(1)) != int(author_id):
            raise PermissionError("cannot remove others' annotations")
    del lines[index]
    save_text(key, "\n".join(lines) + ("\n" if lines else ""))
    return key


def list_file_annotations(category: str, item_rel_base: str) -> list[str]:
    """Return all annotation entries for a file.

    Each entry is returned as a raw log line. If the log does not exist,
    an empty list is returned."""
    key = _annotation_path(category, item_rel_base)
    return _read_annotation_lines(key)
