from __future__ import annotations

from datetime import datetime, UTC

from storage_spaces import read_text, save_text, ensure_dir


def _annotation_path(category: str, item_rel_base: str) -> str:
    cat = category.strip().strip("/")
    item = item_rel_base.strip().strip("/")
    return f"logs/annotations/{cat}/{item}.log"


def add_file_annotation(category: str, item_rel_base: str, author: str, note: str) -> str:
    """Append a note about a file to its annotation log.

    Returns the storage path of the log file."""
    key = _annotation_path(category, item_rel_base)
    ensure_dir("/".join(key.split("/")[:-1]))
    try:
        existing = read_text(key)
    except Exception:
        existing = ""
    ts = datetime.now(UTC).strftime("%Y-%m-%d")
    author_disp = author if author.startswith("@") else f"@{author}"
    entry = f"[{ts}] {author_disp}: {note}"
    save_text(key, existing + entry + "\n")
    return key


def list_file_annotations(category: str, item_rel_base: str) -> list[str]:
    """Return all annotation entries for a file.

    Each entry is returned as a raw log line. If the log does not exist,
    an empty list is returned.
    """
    key = _annotation_path(category, item_rel_base)
    try:
        content = read_text(key)
    except Exception:
        return []
    return [line for line in content.splitlines() if line.strip()]
