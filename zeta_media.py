"""Project ZETA uploads: pictures and videos shown inline, and profile pictures.

Files are identified by their first bytes, never by the name or type the
browser sent, so only formats a browser plays inline are stored and served:
PNG, JPEG, GIF and WebP pictures, and MP4, MOV and WebM videos. Each file is
saved under a random name in the folder of the conversation it belongs to,
so serving it can check the viewer may read that conversation.

Every function takes the storage backend (``storage_spaces``) as its first
argument.
"""

from __future__ import annotations

import os
import re
import secrets
from typing import Any, BinaryIO

MAX_BYTES = 50 * 1024 * 1024
MAX_NAME_LENGTH = 120
_SNIFF_BYTES = 32
_FILE_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|gif|webp|mp4|webm)$")

# extension -> (kind, content type)
_FORMATS: dict[str, tuple[str, str]] = {
    "png": ("image", "image/png"),
    "jpg": ("image", "image/jpeg"),
    "gif": ("image", "image/gif"),
    "webp": ("image", "image/webp"),
    # QuickTime files from phones use the same ISO container, and browsers
    # only play them inline when served as MP4.
    "mp4": ("video", "video/mp4"),
    "webm": ("video", "video/webm"),
}


class UploadRejected(ValueError):
    """The file is empty, too large or not a supported picture or video."""


def sniff(head: bytes) -> str | None:
    """The extension for a supported format, judged from the file's first bytes."""

    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[4:8] == b"ftyp":
        # HEIC/AVIF stills share the container; browsers do not play them as video.
        if head[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"avif", b"avis"):
            return None
        return "mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    return None


def is_media_file(name: str) -> bool:
    return bool(_FILE_RE.fullmatch(str(name or "")))


def content_type(name: str) -> str:
    return _FORMATS[name.rsplit(".", 1)[1]][1]


def clean_name(value: Any) -> str:
    name = os.path.basename(str(value or "").replace("\\", "/")).strip()
    name = "".join(char for char in name if char.isprintable())
    return name[:MAX_NAME_LENGTH] or "upload"


def file_size(fileobj: BinaryIO) -> int:
    fileobj.seek(0, os.SEEK_END)
    size = fileobj.tell()
    fileobj.seek(0)
    return size


def store(
    backend,
    folder: str,
    fileobj: BinaryIO,
    *,
    filename: str = "",
    images_only: bool = False,
) -> dict[str, Any]:
    """Check and save an upload under ``folder``; return its attachment record."""

    size = file_size(fileobj)
    if size <= 0:
        raise UploadRejected("The file is empty.")
    if size > MAX_BYTES:
        raise UploadRejected(f"Files can be at most {MAX_BYTES // (1024 * 1024)} MB.")
    extension = sniff(fileobj.read(_SNIFF_BYTES))
    fileobj.seek(0)
    if extension is None:
        raise UploadRejected("Upload a picture (PNG, JPEG, GIF, WebP) or a video (MP4, MOV, WebM).")
    kind, media_type = _FORMATS[extension]
    if images_only and kind != "image":
        raise UploadRejected("Upload a picture: PNG, JPEG, GIF or WebP.")

    name = f"{secrets.token_hex(16)}.{extension}"
    backend.save_text(f"{folder}/{name}", fileobj, content_type=media_type)
    return {"file": name, "kind": kind, "size": size, "name": clean_name(filename)}


def clean_attachment(raw: Any) -> dict[str, Any] | None:
    """A stored attachment record, or ``None`` when it is missing or malformed."""

    if not isinstance(raw, dict) or not is_media_file(raw.get("file")):
        return None
    try:
        size = max(0, int(raw.get("size") or 0))
    except (TypeError, ValueError):
        size = 0
    return {
        "file": raw["file"],
        "kind": _FORMATS[raw["file"].rsplit(".", 1)[1]][0],
        "size": size,
        "name": clean_name(raw.get("name")),
    }


def delete(backend, folder: str, name: str | None) -> None:
    if name and is_media_file(name):
        try:
            backend.delete_file(f"{folder}/{name}")
        except FileNotFoundError:
            pass


def delete_folder(backend, folder: str) -> None:
    for name, _size, _modified in backend.list_tree(folder):
        backend.delete_file(f"{folder}/{name}")


def sweep(backend, folder: str, *, older_than: float) -> int:
    """Delete files below ``folder`` last written before the epoch time ``older_than``."""

    removed = 0
    for name, _size, modified in backend.list_tree(folder):
        if modified is not None and modified < older_than:
            backend.delete_file(f"{folder}/{name}")
            removed += 1
    return removed


__all__ = [
    "MAX_BYTES",
    "UploadRejected",
    "clean_attachment",
    "content_type",
    "delete",
    "delete_folder",
    "is_media_file",
    "sniff",
    "store",
    "sweep",
]
