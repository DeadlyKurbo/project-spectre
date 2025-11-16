"""Static tech specs for the GU7 fleet viewer."""
from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent
from typing import Any
from urllib.parse import quote


_DEF_VIEWBOX = "0 0 640 360"


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


@dataclass(frozen=True, slots=True)
class Gu7Ship:
    """Represents a GU7 fleet vessel with the fields used by the viewer."""

    slug: str
    name: str
    call_sign: str
    role: str
    class_name: str
    manufacturer: str
    length_m: float
    beam_m: float
    height_m: float
    mass_tons: float
    crew: str
    cargo_tons: float
    max_speed_ms: int
    jump_range_ly: int
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


_RESOLUTE_ANGLES = (
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

_SERAPH_ANGLES = (
    _encode_svg(
        """
        <path d=\"M320 36 L368 96 L560 120 L368 150 L320 324 L272 150 L80 120 L272 96 Z\"/>
        <path d=\"M320 64 L352 112 L472 124 L352 140 L320 252 L288 140 L168 124 L288 112 Z\" opacity=\"0.75\"/>
        <path d=\"M320 92 L332 120 L320 200 L308 120 Z\" opacity=\"0.5\"/>
        <path d=\"M320 252 L364 300 L320 324 L276 300 Z\"/>
        """
    ),
    _encode_svg(
        """
        <path d=\"M120 200 L320 96 L540 120 L520 200 L320 288 L140 260 Z\"/>
        <path d=\"M320 120 L460 140 L440 192 L300 244 L200 224 L220 172 Z\" opacity=\"0.7\"/>
        <path d=\"M360 160 L380 192 L320 216 L300 200 Z\" opacity=\"0.5\"/>
        <path d=\"M220 172 L260 184 L240 224\"/>
        """
    ),
)

_ATLAS_ANGLES = (
    _encode_svg(
        """
        <path d=\"M72 188 L140 124 L320 88 L500 124 L568 188 L500 252 L320 288 L140 252 Z\"/>
        <path d=\"M140 124 L320 140 L500 124\" opacity=\"0.5\"/>
        <path d=\"M140 252 L320 236 L500 252\" opacity=\"0.5\"/>
        <path d=\"M320 88 L320 288\"/>
        <path d=\"M220 160 L420 160 L420 216 L220 216 Z\"/>
        """
    ),
    _encode_svg(
        """
        <path d=\"M120 208 L220 148 L420 132 L540 176 L520 252 L320 304 L160 276 Z\"/>
        <path d=\"M220 148 L340 176 L460 172 L440 228 L320 260 L220 232 Z\" opacity=\"0.65\"/>
        <path d=\"M200 212 L320 200 L420 216\"/>
        <path d=\"M320 152 L360 188 L320 248 L280 188 Z\" opacity=\"0.45\"/>
        """
    ),
)

_MERIDIAN_ANGLES = (
    _encode_svg(
        """
        <path d=\"M320 44 L360 108 L512 132 L360 160 L320 316 L280 160 L128 132 L280 108 Z\"/>
        <path d=\"M320 88 L344 124 L424 136 L344 148 L320 236 L296 148 L216 136 L296 124 Z\" opacity=\"0.7\"/>
        <path d=\"M320 236 L352 276 L320 308 L288 276 Z\"/>
        <path d=\"M320 152 L332 184 L320 212 L308 184 Z\" opacity=\"0.45\"/>
        """
    ),
    _encode_svg(
        """
        <path d=\"M160 204 L320 120 L500 132 L520 200 L360 280 L200 256 Z\"/>
        <path d=\"M320 136 L420 152 L428 196 L320 236 L240 220 L232 176 Z\" opacity=\"0.65\"/>
        <path d=\"M280 176 L320 188 L352 212\"/>
        <path d=\"M232 176 L248 220\"/>
        """
    ),
)

_SHIPS: tuple[Gu7Ship, ...] = (
    Gu7Ship(
        slug="resolute",
        name="Resolute",
        call_sign="VX-77",
        role="Command Frigate",
        class_name="Vigilant-class",
        manufacturer="GU7 Naval Works",
        length_m=142.6,
        beam_m=38.4,
        height_m=26.8,
        mass_tons=860.0,
        crew="12 officers + tactical AI",
        cargo_tons=210.0,
        max_speed_ms=312,
        jump_range_ly=18,
        weapons=(
            "Quad-linked particle lances",
            "6x Ares point-defense rails",
            "Dorsal missile bay (24 cells)",
        ),
        systems=(
            "Tri-core quantum nav",
            "Fleet-link battlespace uplink",
            "Aegis Mk.IX shield lattice",
        ),
        summary="Flagship of the GU7 spearhead, Resolute carries the encrypted Fleet-Link core and coordinates long-range task forces without exposing command ships to the frontline.",
        badge="Battlegroup Lead",
        tagline="Operational nerve center for expeditionary pushes.",
        image_angles=_RESOLUTE_ANGLES,
    ),
    Gu7Ship(
        slug="seraph",
        name="Seraph",
        call_sign="SK-13",
        role="Recon Corvette",
        class_name="Specter-class",
        manufacturer="GU7 Blackworks",
        length_m=88.2,
        beam_m=21.6,
        height_m=14.3,
        mass_tons=320.0,
        crew="4 pilots + drone wing",
        cargo_tons=42.0,
        max_speed_ms=428,
        jump_range_ly=22,
        weapons=(
            "2x ionized rail carbines",
            "Adaptive EMP web",
            "Retractable micro-missile trays",
        ),
        systems=(
            "Ghostfield optical cloak",
            "Threaded sensor needles",
            "Drone bay for 6 recon skiffs",
        ),
        summary="Seraph scouts hostile sectors silently, painting quantum-safe jump corridors for the rest of the fleet while feeding telemetry back to Resolute in real time.",
        badge="Stealth Division",
        tagline="Invisible eyes for deep-vector approach lanes.",
        image_angles=_SERAPH_ANGLES,
    ),
    Gu7Ship(
        slug="atlas",
        name="Atlas",
        call_sign="HL-02",
        role="Heavy Lifter",
        class_name="Anchor-class",
        manufacturer="GU7 Atlas Foundry",
        length_m=196.4,
        beam_m=52.1,
        height_m=41.0,
        mass_tons=1420.0,
        crew="18 riggers",
        cargo_tons=820.0,
        max_speed_ms=246,
        jump_range_ly=14,
        weapons=(
            "Dual spinal mass drivers",
            "Twin flak curtain arrays",
            "Modular utility hardpoints",
        ),
        systems=(
            "Grav-beam cargo cradle",
            "Siege-rated shield sails",
            "Autonomous repair tenders",
        ),
        summary="Atlas brings planetary foundry blocks, armored vehicles, and colony cores in a single run, unfolding the GU7 staging lattice within hours of arrival.",
        badge="Logistics Core",
        tagline="Moves entire outposts without breaking formation.",
        image_angles=_ATLAS_ANGLES,
    ),
    Gu7Ship(
        slug="meridian",
        name="Meridian",
        call_sign="EX-19",
        role="Long-Range Explorer",
        class_name="Venture-class",
        manufacturer="GU7 Cartography",
        length_m=112.7,
        beam_m=29.4,
        height_m=19.8,
        mass_tons=540.0,
        crew="7 explorers",
        cargo_tons=118.0,
        max_speed_ms=368,
        jump_range_ly=27,
        weapons=(
            "2x vector-tuned laser turrets",
            "Deployable probe torpedoes",
            "Countermeasure spool",
        ),
        systems=(
            "Stellar cartography vault",
            "Slipstream weather array",
            "Bio-dome science lab",
        ),
        summary="Meridian sweeps ahead of the fleet to chart supply corridors, monitor stellar weather, and seed entangled beacons for precision re-entry of heavy transports.",
        badge="Pathfinder Wing",
        tagline="Draws the map while the fleet is still en route.",
        image_angles=_MERIDIAN_ANGLES,
    ),
)


def get_gu7_ships() -> tuple[Gu7Ship, ...]:
    """Return a tuple containing all configured GU7 ships."""

    return _SHIPS


def get_ship_by_slug(slug: str) -> Gu7Ship | None:
    """Find a ship by ``slug`` returning ``None`` when missing."""

    slug_norm = (slug or "").strip().lower()
    for ship in _SHIPS:
        if ship.slug == slug_norm:
            return ship
    return None


__all__ = ["Gu7Ship", "get_gu7_ships", "get_ship_by_slug"]
