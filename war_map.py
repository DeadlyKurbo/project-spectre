"""War map data structures and persistence helpers."""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, Mapping

from constants import ROOT_PREFIX
from storage_spaces import read_json, write_json

logger = logging.getLogger(__name__)

_PYRO_STATE_FILENAME = "operations/pyro-war-state.json"
PYRO_WAR_STATE_PATH = (
    f"{ROOT_PREFIX}/{_PYRO_STATE_FILENAME}" if ROOT_PREFIX else _PYRO_STATE_FILENAME
)


PYRO_SYSTEM_BODIES = [
    {
        "id": "pyro-primary",
        "name": "Pyro",
        "designation": "K-Type Primary",
        "summary": (
            "Massive K-type star supplying radiation and gravimetric anchor points for "
            "the entire theatre. Monitoring arrays report steady output with intermittent "
            "flare storms."
        ),
    },
    {
        "id": "pyro-i",
        "name": "Pyro I",
        "designation": "Forge World Remnant",
        "summary": (
            "Tidally locked ember sphere. Old refinery shafts vent plasma and only "
            "shielded drones can skim its surface."
        ),
    },
    {
        "id": "pyro-ii",
        "name": "Pyro II",
        "designation": "Cracked Desert Sphere",
        "summary": (
            "Wind-scoured plateaus host scattered exile camps. Sensor towers are leased "
            "for Spectre comm relays."
        ),
    },
    {
        "id": "pyro-iii",
        "name": "Pyro III",
        "designation": "Border Outposts",
        "summary": (
            "Primary muster world for local militias. Acts as staging ground for response "
            "teams sweeping the inner belts."
        ),
    },
    {
        "id": "pyro-iv",
        "name": "Pyro IV",
        "designation": "Volcanic Planetoid",
        "summary": (
            "Explosive magma fields and salvage gangs competing for heat-resistant alloys "
            "dominate this orbit."
        ),
    },
    {
        "id": "soul",
        "name": "Soul",
        "designation": "Listening Outpost",
        "summary": (
            "Converted tanker hull turned pirate embassy. Spectre taps hidden antenna "
            "arrays for forward telemetry."
        ),
    },
    {
        "id": "ruin-station",
        "name": "Ruin Station",
        "designation": "Freebooter Citadel",
        "summary": (
            "Asteroid hollowed into a smuggler megadock. Current détente allows Spectre "
            "strike craft to refuel covertly."
        ),
    },
    {
        "id": "the-belt",
        "name": "The Belt",
        "designation": "Asteroid Band",
        "summary": (
            "Dense debris field rich in salvage frames. Convoys weave through marked "
            "channels escorted by corvettes."
        ),
    },
    {
        "id": "pyro-v",
        "name": "Pyro V",
        "designation": "Fractured Exo World",
        "summary": (
            "Steam-choked jungles hide cartel vaults. Recon flights track thermal vents for "
            "strike targeting."
        ),
    },
    {
        "id": "pyro-vi",
        "name": "Pyro VI",
        "designation": "Ice Giant",
        "summary": (
            "Hydrogen giant with pirate drift dens buried inside the magnetosphere. Drone "
            "carriers patrol polar orbits."
        ),
    },
    {
        "id": "nyx-jump",
        "name": "Nyx Jump Point",
        "designation": "Outer System Jump",
        "summary": (
            "Primary outbound throat toward Nyx. Pirate blockade runners favor this chain "
            "for slipping UEE nets."
        ),
    },
    {
        "id": "stanton-jump",
        "name": "Stanton Jump Point",
        "designation": "UEE Corridor",
        "summary": (
            "Inbound gate for Stanton reinforcements. Heavily trafficked with humanitarian "
            "caravans and bait freighters."
        ),
    },
]

PYRO_WAR_SECTORS = [
    {
        "id": "inner",
        "title": "Inner Ember Chain",
        "description": (
            "Planets closest to the primary, used for fuel skimming and rapid strike "
            "preparation."
        ),
        "bodies": ["pyro-i", "pyro-ii", "pyro-iii"],
    },
    {
        "id": "mid",
        "title": "Mid-Belt Holdings",
        "description": (
            "Stations and planetoids that form the heart of our logistics web inside Pyro."
        ),
        "bodies": ["pyro-iv", "soul", "ruin-station", "the-belt"],
    },
    {
        "id": "outer",
        "title": "Outer Approach",
        "description": (
            "Outer worlds and jump points that dictate whether Pyro stays open to the verse."
        ),
        "bodies": ["pyro-v", "pyro-vi", "nyx-jump", "stanton-jump"],
    },
]

PYRO_WAR_ORBITAL_LAYOUT = [
    {
        "label": "Inner Orbit",
        "radius": 12,
        "bodies": [{"id": "pyro-i", "angle": 200, "align": "center"}],
    },
    {
        "label": "Rapid Burn Chain",
        "radius": 22,
        "bodies": [
            {"id": "pyro-ii", "angle": 300, "align": "right"},
            {"id": "pyro-iii", "angle": 40, "align": "left"},
        ],
    },
    {
        "label": "Trade Arc",
        "radius": 34,
        "bodies": [
            {"id": "pyro-iv", "angle": 240, "align": "right"},
            {"id": "soul", "angle": 350, "align": "left"},
            {"id": "ruin-station", "angle": 70, "align": "left"},
            {"id": "the-belt", "angle": 150, "align": "left"},
        ],
    },
    {
        "label": "Pyro V Orbit",
        "radius": 41,
        "bodies": [{"id": "pyro-v", "angle": 220, "align": "right"}],
    },
    {
        "label": "Pyro VI Orbit",
        "radius": 46,
        "bodies": [{"id": "pyro-vi", "angle": 25, "align": "left"}],
    },
    {
        "label": "Jump Shell",
        "radius": 48,
        "dashed": True,
        "bodies": [
            {"id": "nyx-jump", "angle": 320, "align": "right"},
            {"id": "stanton-jump", "angle": 140, "align": "left"},
        ],
    },
]

PYRO_WAR_STATE_LABELS = {
    "friendly": "Friendly Territory",
    "contested": "Attack Order",
    "inactive": "Inactive",
}

PYRO_WAR_STATUS_CHOICES = (
    {"value": "active", "label": "Active War"},
    {"value": "victory", "label": "Victory Declared"},
    {"value": "retreat", "label": "Strategic Withdrawal"},
)

PYRO_WAR_STATE_CHOICES = (
    {
        "value": "friendly",
        "label": "Friendly",
        "description": "Supply lines secured and Spectre patrols active.",
    },
    {
        "value": "contested",
        "label": "Contested",
        "description": "Priority attack focus assigned to this body.",
    },
    {
        "value": "inactive",
        "label": "Inactive",
        "description": "No current orders — monitor only.",
    },
)

PYRO_WAR_DEFAULT_FOCUS = (
    "Hold the Trade Arc and jump shell to keep convoys moving into Stanton."
)

_DEFAULT_BATTLE_STATE = {
    "pyro-i": "inactive",
    "pyro-ii": "inactive",
    "pyro-iii": "friendly",
    "pyro-iv": "contested",
    "soul": "friendly",
    "ruin-station": "friendly",
    "the-belt": "contested",
    "pyro-v": "contested",
    "pyro-vi": "friendly",
    "nyx-jump": "contested",
    "stanton-jump": "friendly",
}

_ALLOWED_STATES = set(PYRO_WAR_STATE_LABELS.keys())
_ALLOWED_WAR_STATUSES = {option["value"] for option in PYRO_WAR_STATUS_CHOICES}

_DEFAULT_WAR_STATUS = "active"
_DEFAULT_WAR_OUTCOME_MESSAGE = ""


def _default_battle_map() -> dict[str, str]:
    base = {body["id"]: "inactive" for body in PYRO_SYSTEM_BODIES if body["id"] != "pyro-primary"}
    base.update(_DEFAULT_BATTLE_STATE)
    return base


def _normalize_state(value: Any) -> str:
    key = str(value or "").strip().lower()
    if key in _ALLOWED_STATES:
        return key
    return "inactive"


def _normalize_war_status(value: Any) -> str:
    key = str(value or "").strip().lower()
    if key in _ALLOWED_WAR_STATUSES:
        return key
    return _DEFAULT_WAR_STATUS


def sanitize_pyro_war_state(
    battle_readiness: Mapping[str, Any] | None,
    attack_focus: Any,
    fleet_assignments: Mapping[str, Any] | None = None,
    war_status: Any | None = None,
    war_outcome_message: Any | None = None,
) -> dict[str, Any]:
    readiness = _default_battle_map()
    if isinstance(battle_readiness, Mapping):
        for body_id in list(readiness.keys()):
            readiness[body_id] = _normalize_state(battle_readiness.get(body_id))

    focus = str(attack_focus or "").strip()
    assignments: dict[str, list[str]] = {}
    if isinstance(fleet_assignments, Mapping):
        allowed_ids = set(readiness.keys())
        for body_id, vessels in fleet_assignments.items():
            if body_id not in allowed_ids:
                continue
            normalized: list[str] = []
            if isinstance(vessels, (list, tuple, set)):
                for vessel_id in vessels:
                    trimmed = str(vessel_id or "").strip()
                    if trimmed:
                        normalized.append(trimmed)
            else:
                trimmed = str(vessels or "").strip()
                if trimmed:
                    normalized.append(trimmed)
            if normalized:
                assignments[body_id] = normalized

    status = _normalize_war_status(war_status)
    message = str(war_outcome_message or _DEFAULT_WAR_OUTCOME_MESSAGE).strip()
    if len(message) > 500:
        message = message[:500]

    return {
        "battle_readiness": readiness,
        "attack_focus": focus,
        "fleet_assignments": assignments,
        "war_status": status,
        "war_outcome_message": message,
    }


def load_pyro_war_state(*, with_etag: bool = False):
    """Return the persisted Pyro war state, falling back to defaults."""

    try:
        data, etag = read_json(PYRO_WAR_STATE_PATH, with_etag=True)
    except FileNotFoundError:
        payload = sanitize_pyro_war_state(_DEFAULT_BATTLE_STATE, PYRO_WAR_DEFAULT_FOCUS)
        return (payload, None) if with_etag else payload
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("Failed to load Pyro war state; serving defaults")
        payload = sanitize_pyro_war_state(_DEFAULT_BATTLE_STATE, PYRO_WAR_DEFAULT_FOCUS)
        return (payload, None) if with_etag else payload

    payload = sanitize_pyro_war_state(
        data.get("battle_readiness") if isinstance(data, Mapping) else None,
        data.get("attack_focus") if isinstance(data, Mapping) else None,
        data.get("fleet_assignments") if isinstance(data, Mapping) else None,
        data.get("war_status") if isinstance(data, Mapping) else None,
        data.get("war_outcome_message") if isinstance(data, Mapping) else None,
    )
    if with_etag:
        return payload, etag
    return payload


def save_pyro_war_state(
    battle_readiness: Mapping[str, Any] | None,
    attack_focus: Any,
    fleet_assignments: Mapping[str, Any] | None = None,
    war_status: Any | None = None,
    war_outcome_message: Any | None = None,
    *,
    etag: str | None = None,
) -> bool:
    payload = sanitize_pyro_war_state(
        battle_readiness,
        attack_focus,
        fleet_assignments,
        war_status,
        war_outcome_message,
    )
    return write_json(PYRO_WAR_STATE_PATH, payload, etag=etag)


def pyro_war_body_listing(include_primary: bool = False) -> list[dict[str, Any]]:
    bodies = deepcopy(PYRO_SYSTEM_BODIES)
    if include_primary:
        return bodies
    return [body for body in bodies if body.get("id") != "pyro-primary"]

