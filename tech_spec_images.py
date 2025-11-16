"""Helpers for managing GU7 tech spec image uploads."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import io
from typing import Dict, Tuple

from storage_spaces import read_json, save_json, save_text, read_file

TECH_SPEC_IMAGE_PREFIX = "owner/tech-specs"
_IMAGE_MANIFEST_KEY = f"{TECH_SPEC_IMAGE_PREFIX}/images.json"


@dataclass(slots=True)
class TechSpecImage:
    slug: str
    key: str
    updated_at: str


def _normalize_slug(slug: str) -> str:
    return (slug or "").strip().lower().replace(" ", "-")


def _image_key(slug: str) -> str:
    normalized = _normalize_slug(slug)
    if not normalized:
        raise ValueError("Ship slug is required")
    return f"{TECH_SPEC_IMAGE_PREFIX}/{normalized}.png"


def _coerce_manifest(data: dict | None) -> Dict[str, TechSpecImage]:
    images: Dict[str, TechSpecImage] = {}
    if not isinstance(data, dict):
        return images
    raw = data.get("images")
    if not isinstance(raw, dict):
        return images
    for slug, entry in raw.items():
        normalized = _normalize_slug(slug)
        key = str(entry.get("key") or "").strip() if isinstance(entry, dict) else ""
        updated = str(entry.get("updated_at") or "").strip() if isinstance(entry, dict) else ""
        if not normalized or not key:
            continue
        images[normalized] = TechSpecImage(slug=normalized, key=key, updated_at=updated)
    return images


def list_ship_images() -> Dict[str, Dict[str, str]]:
    """Return mapping of slug -> metadata for uploaded images."""

    try:
        data = read_json(_IMAGE_MANIFEST_KEY)
    except FileNotFoundError:
        return {}
    manifest = _coerce_manifest(data)
    return {
        slug: {"key": image.key, "updated_at": image.updated_at}
        for slug, image in manifest.items()
    }


def save_ship_image(slug: str, data: bytes) -> Dict[str, str]:
    """Persist ``data`` as the PNG for ``slug`` returning metadata."""

    if not data:
        raise ValueError("Image data is required")
    normalized = _normalize_slug(slug)
    if not normalized:
        raise ValueError("Ship slug is required")
    key = _image_key(normalized)
    buffer = io.BytesIO(data)
    buffer.seek(0)
    save_text(key, buffer, content_type="image/png")
    manifest = list_ship_images()
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest[normalized] = {"key": key, "updated_at": updated_at}
    save_json(_IMAGE_MANIFEST_KEY, {"images": manifest})
    return manifest[normalized]


def get_ship_image_bytes(slug: str) -> Tuple[bytes, str]:
    """Return the stored image bytes + content type for ``slug``."""

    normalized = _normalize_slug(slug)
    if not normalized:
        raise FileNotFoundError("Missing ship slug")
    manifest = list_ship_images()
    entry = manifest.get(normalized)
    key = entry.get("key") if entry else _image_key(normalized)
    return read_file(key)


__all__ = [
    "TECH_SPEC_IMAGE_PREFIX",
    "TechSpecImage",
    "list_ship_images",
    "save_ship_image",
    "get_ship_image_bytes",
]
