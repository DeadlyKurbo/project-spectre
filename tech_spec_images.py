"""Helpers for managing FDD tech spec image uploads."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import io
from typing import Callable, Dict, Tuple

from storage_spaces import read_json, save_json, save_text, read_file

TECH_SPEC_IMAGE_PREFIX = "owner/tech-specs"
_IMAGE_MANIFEST_KEY = f"{TECH_SPEC_IMAGE_PREFIX}/images.json"


@dataclass(slots=True)
class TechSpecImage:
    slug: str
    key: str
    updated_at: str
    content_type: str


@dataclass(frozen=True)
class _ImageFormat:
    extension: str
    content_type: str
    label: str
    matcher: Callable[[bytes], bool]


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"


def _matches_webp(data: bytes) -> bool:
    return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"


_IMAGE_FORMATS: Tuple[_ImageFormat, ...] = (
    _ImageFormat(
        extension="png",
        content_type="image/png",
        label="PNG",
        matcher=lambda data: data.startswith(_PNG_SIGNATURE),
    ),
    _ImageFormat(
        extension="jpg",
        content_type="image/jpeg",
        label="JPEG",
        matcher=lambda data: data.startswith(_JPEG_SIGNATURE),
    ),
    _ImageFormat(
        extension="jpeg",
        content_type="image/jpeg",
        label="JPEG",
        matcher=lambda data: data.startswith(_JPEG_SIGNATURE),
    ),
    _ImageFormat(
        extension="webp",
        content_type="image/webp",
        label="WebP",
        matcher=_matches_webp,
    ),
)


def _normalize_slug(slug: str) -> str:
    return (slug or "").strip().lower().replace(" ", "-")


def _image_key(slug: str, extension: str = "png") -> str:
    normalized = _normalize_slug(slug)
    if not normalized:
        raise ValueError("Ship slug is required")
    ext = extension.lstrip(".").lower() or "png"
    return f"{TECH_SPEC_IMAGE_PREFIX}/{normalized}.{ext}"


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
        content_type = (
            str(entry.get("content_type") or "").strip()
            if isinstance(entry, dict)
            else ""
        )
        if not normalized or not key:
            continue
        images[normalized] = TechSpecImage(
            slug=normalized,
            key=key,
            updated_at=updated,
            content_type=content_type or "image/png",
        )
    return images


def list_ship_images() -> Dict[str, Dict[str, str]]:
    """Return mapping of slug -> metadata for uploaded images."""

    try:
        data = read_json(_IMAGE_MANIFEST_KEY)
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


def save_ship_image(
    slug: str, data: bytes, *, content_type: str = "image/png", extension: str = "png"
) -> Dict[str, str]:
    """Persist ``data`` for ``slug`` returning metadata."""

    if not data:
        raise ValueError("Image data is required")
    normalized = _normalize_slug(slug)
    if not normalized:
        raise ValueError("Ship slug is required")
    sanitized_extension = extension.lstrip(".").lower() or "png"
    key = _image_key(normalized, sanitized_extension)
    buffer = io.BytesIO(data)
    buffer.seek(0)
    save_text(key, buffer, content_type=content_type or "image/png")
    manifest = list_ship_images()
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest[normalized] = {
        "key": key,
        "updated_at": updated_at,
        "content_type": content_type or "image/png",
    }
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
    data, content_type = read_file(key)
    if entry:
        stored_type = entry.get("content_type")
        if stored_type:
            content_type = stored_type
    return data, content_type


def detect_image_format(data: bytes) -> Tuple[str, str] | None:
    """Identify supported image formats by signature.

    Returns a tuple of ``(extension, content_type)`` for supported formats
    or ``None`` when the bytes do not match an allowed type.
    """

    if not data:
        return None
    for fmt in _IMAGE_FORMATS:
        if fmt.matcher(data):
            return fmt.extension, fmt.content_type
    return None


def image_format_labels() -> Tuple[str, ...]:
    """Return display labels for supported formats without duplicates."""

    labels: list[str] = []
    for fmt in _IMAGE_FORMATS:
        if fmt.label not in labels:
            labels.append(fmt.label)
    return tuple(labels)


def accepted_image_content_types() -> Tuple[str, ...]:
    """Return the MIME types accepted by tech spec uploads."""

    content_types: list[str] = []
    for fmt in _IMAGE_FORMATS:
        if fmt.content_type not in content_types:
            content_types.append(fmt.content_type)
    return tuple(content_types)


__all__ = [
    "TECH_SPEC_IMAGE_PREFIX",
    "TechSpecImage",
    "list_ship_images",
    "save_ship_image",
    "get_ship_image_bytes",
    "detect_image_format",
    "image_format_labels",
    "accepted_image_content_types",
]
