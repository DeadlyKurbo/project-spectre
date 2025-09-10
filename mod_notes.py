from __future__ import annotations

from datetime import UTC, datetime

from storage_spaces import read_text, save_text, ensure_dir


def _note_path(user_id: int | str) -> str:
    uid = str(user_id).strip()
    return f"logs/mod_notes/{uid}.log"


def add_member_note(user_id: int | str, author: int | str, note: str) -> str:
    """Append a moderation note about a guild member.

    Notes are stored under ``logs/mod_notes/<user_id>.log`` with a simple
    timestamped format. The function returns the storage path of the log file."""

    key = _note_path(user_id)
    ensure_dir("/".join(key.split("/")[:-1]))
    try:
        existing = read_text(key)
    except Exception:
        existing = ""
    ts = datetime.now(UTC).strftime("%Y-%m-%d")
    if isinstance(author, int) or (isinstance(author, str) and str(author).isdigit()):
        author_disp = f"<@{int(author)}>"
    else:
        author_disp = f"@{str(author).lstrip('@')}"
    entry = f"[{ts}] {author_disp}: {note}"
    save_text(key, existing + entry + "\n")
    return key


def list_member_notes(user_id: int | str) -> list[str]:
    """Return all moderation notes for ``user_id``."""
    key = _note_path(user_id)
    try:
        content = read_text(key)
    except Exception:
        return []
    return [line for line in content.splitlines() if line.strip()]
