"""Image registry for admin-defined visual replacements.

Admins can upload small images keyed by a human-friendly slug (for example
"spectre" or "hq"). The registry is stored in ``storage_spaces`` so branding
changes propagate to every deployment. Helper functions keep manifest updates
consistent and expose a simple API for routers and templates.
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

_DEFINITION_IMAGE_PREFIX = "branding/definitions"
_DEFINITION_IMAGE_MANIFEST = f"{_DEFINITION_IMAGE_PREFIX}/images.json"


@dataclass(slots=True)
class DefinitionImage:
    slug: str
    key: str
    updated_at: str
    content_type: str


def normalize_definition_slug(value: str) -> str:
    """Convert ``value`` into a safe slug used for storage keys."""

    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug


def _image_key(slug: str, extension: str = "png") -> str:
    normalized = normalize_definition_slug(slug)
    if not normalized:
        raise ValueError("Definition slug is required")
    ext = extension.lstrip(".").lower() or "png"
    return f"{_DEFINITION_IMAGE_PREFIX}/{normalized}.{ext}"


def _coerce_manifest(data: dict | None) -> Dict[str, DefinitionImage]:
    images: Dict[str, DefinitionImage] = {}
    if not isinstance(data, dict):
        return images

    raw = data.get("images")
    if not isinstance(raw, dict):
        return images

    for slug, entry in raw.items():
        normalized = normalize_definition_slug(slug)
        key = str(entry.get("key") or "").strip() if isinstance(entry, dict) else ""
        updated = str(entry.get("updated_at") or "").strip() if isinstance(entry, dict) else ""
        content_type = (
            str(entry.get("content_type") or "").strip()
            if isinstance(entry, dict)
            else ""
        )
        if not normalized or not key:
            continue
        images[normalized] = DefinitionImage(
            slug=normalized,
            key=key,
            updated_at=updated,
            content_type=content_type or "image/png",
        )
    return images


def list_definition_images() -> Dict[str, Dict[str, str]]:
    """Return mapping of slug -> metadata for uploaded definition images."""

    try:
        from storage_spaces import read_json  # local import to avoid cycle in tests

        data = read_json(_DEFINITION_IMAGE_MANIFEST)
    except FileNotFoundError:
        return {}
    manifest = _coerce_manifest(data)
    return {
        slug: {
            "key": image.key,
            "updated_at": image.updated_at,
            "content_type": image.content_type,
        }
        for slug, image in manifest.items()
    }


def save_definition_image(
    slug: str, data: bytes, *, content_type: str = "image/png", extension: str = "png"
) -> Dict[str, str]:
    """Persist ``data`` for ``slug`` returning manifest metadata."""

    if not data:
        raise ValueError("Image data is required")

    normalized = normalize_definition_slug(slug)
    if not normalized:
        raise ValueError("Definition slug is required")

    sanitized_extension = extension.lstrip(".").lower() or "png"
    key = _image_key(normalized, sanitized_extension)

    buffer = io.BytesIO(data)
    buffer.seek(0)
    save_text(key, buffer, content_type=content_type or "image/png")

    manifest = list_definition_images()
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest[normalized] = {
        "key": key,
        "updated_at": updated_at,
        "content_type": content_type or "image/png",
    }
    save_json(_DEFINITION_IMAGE_MANIFEST, {"images": manifest})
    return manifest[normalized]


def delete_definition_image(slug: str) -> None:
    """Remove the image and manifest entry for ``slug`` if present."""

    normalized = normalize_definition_slug(slug)
    if not normalized:
        return

    manifest = list_definition_images()
    entry = manifest.pop(normalized, None)
    if entry:
        save_json(_DEFINITION_IMAGE_MANIFEST, {"images": manifest})
        try:
            delete_file(entry.get("key"))
        except FileNotFoundError:
            pass


def get_definition_image_bytes(slug: str) -> Tuple[bytes, str]:
    """Return bytes + content type for ``slug``."""

    normalized = normalize_definition_slug(slug)
    if not normalized:
        raise FileNotFoundError("Missing definition slug")

    manifest = list_definition_images()
    entry = manifest.get(normalized)
    key = entry.get("key") if entry else _image_key(normalized)
    data, content_type = read_file(key)
    if entry and entry.get("content_type"):
        content_type = entry["content_type"]
    return data, content_type


__all__ = [
    "accepted_image_content_types",
    "delete_definition_image",
    "detect_image_format",
    "get_definition_image_bytes",
    "image_format_labels",
    "list_definition_images",
    "normalize_definition_slug",
    "save_definition_image",
]
