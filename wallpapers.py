"""Wallpaper registry for page-level backgrounds.

Admins can upload per-page wallpapers that override the default grid
pattern. Wallpapers are stored in ``storage_spaces`` so changes
propagate to every deployment.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Tuple

from storage_spaces import delete_file, read_file, save_json, save_text
from tech_spec_images import (
    accepted_image_content_types,
    detect_image_format,
    image_format_labels,
)

_WALLPAPER_PREFIX = "branding/wallpapers"
_WALLPAPER_MANIFEST = f"{_WALLPAPER_PREFIX}/wallpapers.json"


@dataclass(slots=True)
class Wallpaper:
    slug: str
    key: str
    updated_at: str
    content_type: str


def normalize_wallpaper_slug(value: str) -> str:
    """Convert ``value`` into a safe slug used for storage keys."""

    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug


def _wallpaper_key(slug: str, extension: str = "png") -> str:
    normalized = normalize_wallpaper_slug(slug)
    if not normalized:
        raise ValueError("Wallpaper slug is required")
    ext = extension.lstrip(".").lower() or "png"
    return f"{_WALLPAPER_PREFIX}/{normalized}.{ext}"


def _coerce_manifest(data: dict | None) -> Dict[str, Wallpaper]:
    wallpapers: Dict[str, Wallpaper] = {}
    if not isinstance(data, dict):
        return wallpapers

    raw = data.get("wallpapers")
    if not isinstance(raw, dict):
        return wallpapers

    for slug, entry in raw.items():
        normalized = normalize_wallpaper_slug(slug)
        key = str(entry.get("key") or "").strip() if isinstance(entry, dict) else ""
        updated = str(entry.get("updated_at") or "").strip() if isinstance(entry, dict) else ""
        content_type = (
            str(entry.get("content_type") or "").strip()
            if isinstance(entry, dict)
            else ""
        )
        if not normalized or not key:
            continue
        wallpapers[normalized] = Wallpaper(
            slug=normalized,
            key=key,
            updated_at=updated,
            content_type=content_type or "image/png",
        )
    return wallpapers


def list_wallpapers() -> Dict[str, Dict[str, str]]:
    """Return mapping of slug -> metadata for uploaded wallpapers."""

    try:
        from storage_spaces import read_json  # local import to avoid cycle in tests

        data = read_json(_WALLPAPER_MANIFEST)
    except FileNotFoundError:
        return {}
    manifest = _coerce_manifest(data)
    return {
        slug: {
            "key": wallpaper.key,
            "updated_at": wallpaper.updated_at,
            "content_type": wallpaper.content_type,
        }
        for slug, wallpaper in manifest.items()
    }


def save_wallpaper(
    slug: str, data: bytes, *, content_type: str = "image/png", extension: str = "png"
) -> Dict[str, str]:
    """Persist ``data`` for ``slug`` returning manifest metadata."""

    if not data:
        raise ValueError("Image data is required")

    normalized = normalize_wallpaper_slug(slug)
    if not normalized:
        raise ValueError("Wallpaper slug is required")

    sanitized_extension = extension.lstrip(".").lower() or "png"
    key = _wallpaper_key(normalized, sanitized_extension)

    buffer = io.BytesIO(data)
    buffer.seek(0)
    save_text(key, buffer, content_type=content_type or "image/png")

    manifest = list_wallpapers()
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest[normalized] = {
        "key": key,
        "updated_at": updated_at,
        "content_type": content_type or "image/png",
    }
    save_json(_WALLPAPER_MANIFEST, {"wallpapers": manifest})
    return manifest[normalized]


def delete_wallpaper(slug: str) -> None:
    """Remove the wallpaper and manifest entry for ``slug`` if present."""

    normalized = normalize_wallpaper_slug(slug)
    if not normalized:
        return

    manifest = list_wallpapers()
    entry = manifest.pop(normalized, None)
    if entry:
        save_json(_WALLPAPER_MANIFEST, {"wallpapers": manifest})
        try:
            delete_file(entry.get("key"))
        except FileNotFoundError:
            pass


def get_wallpaper_bytes(slug: str) -> Tuple[bytes, str]:
    """Return bytes + content type for ``slug``."""

    normalized = normalize_wallpaper_slug(slug)
    if not normalized:
        raise FileNotFoundError("Missing wallpaper slug")

    manifest = list_wallpapers()
    entry = manifest.get(normalized)
    key = entry.get("key") if entry else _wallpaper_key(normalized)
    data, content_type = read_file(key)
    if entry and entry.get("content_type"):
        content_type = entry["content_type"]
    return data, content_type


__all__ = [
    "accepted_image_content_types",
    "delete_wallpaper",
    "detect_image_format",
    "get_wallpaper_bytes",
    "image_format_labels",
    "list_wallpapers",
    "normalize_wallpaper_slug",
    "save_wallpaper",
]
