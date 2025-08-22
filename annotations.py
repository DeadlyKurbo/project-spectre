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
    ts = datetime.now(UTC).isoformat()
    entry = f"{ts} {author}: {note}"
    save_text(key, existing + entry + "\n")
    return key
