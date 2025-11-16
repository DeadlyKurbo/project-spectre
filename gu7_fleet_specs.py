"""Dynamic tech specs for the GU7 fleet viewer."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from textwrap import dedent
from typing import Any
from urllib.parse import quote
import logging

from storage_spaces import read_json


_DEF_VIEWBOX = "0 0 640 360"
_SHIP_MANIFEST_KEY = "owner/tech-specs/ships.json"
_logger = logging.getLogger(__name__)


def _encode_svg(body: str) -> str:
    """Return a data URI containing ``body`` wrapped in a hologram SVG template."""

    svg = dedent(
        f"""
        <svg width=\"640\" height=\"360\" viewBox=\"{_DEF_VIEWBOX}\" fill=\"none\" xmlns=\"http://www.w3.org/2000/svg\">
          <defs>
            <linearGradient id=\"scan\" x1=\"0\" y1=\"0\" x2=\"0\" y2=\"1\">
              <stop offset=\"0%\" stop-color=\"#7dd3fc\" stop-opacity=\"0.85\"/>
              <stop offset=\"50%\" stop-color=\"#38bdf8\" stop-opacity=\"0.45\"/>
              <stop offset=\"100%\" stop-color=\"#0ea5e9\" stop-opacity=\"0.2\"/>
            </linearGradient>
          </defs>
          <rect x=\"8\" y=\"8\" width=\"624\" height=\"344\" rx=\"22\" stroke=\"#1d3b58\" stroke-width=\"2.5\" opacity=\"0.4\"/>
          <g stroke=\"url(#scan)\" stroke-width=\"3\" stroke-linecap=\"round\" stroke-linejoin=\"round\" opacity=\"0.92\">
            {body}
          </g>
        </svg>
        """
    ).strip()
    return "data:image/svg+xml;utf8," + quote(svg)


_DEFAULT_HOLOGRAM_ANGLES = (
    _encode_svg(
        """
        <path d=\"M320 24 L368 96 L368 152 L604 180 L368 208 L368 264 L320 336 L272 264 L272 208 L36 180 L272 152 L272 96 Z\"/>
        <path d=\"M320 60 L340 120 L512 180 L340 240 L320 300 L300 240 L128 180 L300 120 Z\" opacity=\"0.75\"/>
        <path d=\"M320 92 L356 180 L320 268 L284 180 Z\" opacity=\"0.5\"/>
        <circle cx=\"320\" cy=\"180\" r=\"24\"/>
        """
    ),
    _encode_svg(
        """
        <path d=\"M80 210 L260 120 L500 80 L580 140 L520 260 L340 300 L140 280 Z\"/>
        <path d=\"M260 120 L340 80 L520 140 L460 220 L300 260 L180 240 Z\" opacity=\"0.75\"/>
        <path d=\"M320 140 L420 160 L380 220 L280 240 Z\" opacity=\"0.5\"/>
        <path d=\"M260 184 L320 200 L360 248\"/>
        """
    ),
)


def _normalize_slug(value: str) -> str:
    slug = (value or "").strip().lower()
    slug = slug.replace(" ", "-")
    allowed = [ch for ch in slug if ch.isalnum() or ch in {"-", "_"}]
    normalized = "".join(allowed).strip("-")
    return normalized


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    text = str(value).strip()
    if not text or text.upper() == "N/A":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _iter_text(value: Any) -> Iterable[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return []
    if isinstance(value, Iterable):
        result = []
        for entry in value:
            if entry is None:
                continue
            result.append(str(entry))
        return result
    return []


def _coerce_text_list(value: Any) -> tuple[str, ...]:
    entries: list[str] = []
    for raw in _iter_text(value):
        text = raw.strip()
        if text:
            entries.append(text)
    return tuple(entries)


def _coerce_angles(value: Any) -> tuple[str, ...]:
    angles = _coerce_text_list(value)
    return angles if angles else _DEFAULT_HOLOGRAM_ANGLES


@dataclass(frozen=True, slots=True)
class Gu7Ship:
    """Represents a GU7 fleet vessel with the fields used by the viewer."""

    slug: str
    name: str
    call_sign: str
    role: str
    class_name: str
    manufacturer: str
    length_m: float | None
    beam_m: float | None
    height_m: float | None
    mass_tons: float | None
    crew: str
    cargo_tons: float | None
    max_speed_ms: float | None
    jump_range_ly: float | None
    weapons: tuple[str, ...]
    systems: tuple[str, ...]
    summary: str
    badge: str
    tagline: str
    image_angles: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-serialisable payload for the template."""

        return {
            "slug": self.slug,
            "name": self.name,
            "call_sign": self.call_sign,
            "role": self.role,
            "class_name": self.class_name,
            "manufacturer": self.manufacturer,
            "length_m": self.length_m,
            "beam_m": self.beam_m,
            "height_m": self.height_m,
            "mass_tons": self.mass_tons,
            "crew": self.crew,
            "cargo_tons": self.cargo_tons,
            "max_speed_ms": self.max_speed_ms,
            "jump_range_ly": self.jump_range_ly,
            "weapons": list(self.weapons),
            "systems": list(self.systems),
            "summary": self.summary,
            "badge": self.badge,
            "tagline": self.tagline,
            "angles": list(self.image_angles),
        }

    @classmethod
    def from_data(cls, value: Any) -> "Gu7Ship" | None:
        if not isinstance(value, dict):
            return None
        slug = _normalize_slug(str(value.get("slug") or value.get("id") or value.get("name") or ""))
        name = str(value.get("name") or "").strip()
        if not slug or not name:
            return None
        call_sign = str(value.get("call_sign") or "").strip()
        role = str(value.get("role") or "").strip()
        class_name = str(value.get("class_name") or "").strip()
        manufacturer = str(value.get("manufacturer") or "").strip()
        crew = str(value.get("crew") or "").strip()
        summary = str(value.get("summary") or "").strip()
        badge = str(value.get("badge") or "").strip()
        tagline = str(value.get("tagline") or "").strip()
        weapons = _coerce_text_list(value.get("weapons"))
        systems = _coerce_text_list(value.get("systems"))
        image_angles = _coerce_angles(value.get("image_angles") or value.get("angles"))
        return cls(
            slug=slug,
            name=name,
            call_sign=call_sign,
            role=role,
            class_name=class_name,
            manufacturer=manufacturer,
            length_m=_parse_float(value.get("length_m")),
            beam_m=_parse_float(value.get("beam_m")),
            height_m=_parse_float(value.get("height_m")),
            mass_tons=_parse_float(value.get("mass_tons")),
            crew=crew,
            cargo_tons=_parse_float(value.get("cargo_tons")),
            max_speed_ms=_parse_float(value.get("max_speed_ms")),
            jump_range_ly=_parse_float(value.get("jump_range_ly")),
            weapons=weapons,
            systems=systems,
            summary=summary,
            badge=badge,
            tagline=tagline,
            image_angles=image_angles,
        )


def _load_ship_manifest() -> tuple[Gu7Ship, ...]:
    try:
        data = read_json(_SHIP_MANIFEST_KEY)
    except FileNotFoundError:
        return ()
    except Exception as exc:  # pragma: no cover - defensive logging
        _logger.warning("Failed to read GU7 ship manifest: %s", exc)
        return ()

    entries = data.get("ships") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return ()

    ships: list[Gu7Ship] = []
    for entry in entries:
        ship = Gu7Ship.from_data(entry)
        if ship is not None:
            ships.append(ship)
    ships.sort(key=lambda ship: (ship.name.lower(), ship.slug))
    return tuple(ships)


def get_gu7_ships() -> tuple[Gu7Ship, ...]:
    """Return a tuple containing all configured GU7 ships."""

    return _load_ship_manifest()


def get_ship_by_slug(slug: str) -> Gu7Ship | None:
    """Find a ship by ``slug`` returning ``None`` when missing."""

    slug_norm = _normalize_slug(slug or "")
    if not slug_norm:
        return None
    for ship in get_gu7_ships():
        if ship.slug == slug_norm:
            return ship
    return None


__all__ = ["Gu7Ship", "get_gu7_ships", "get_ship_by_slug"]
