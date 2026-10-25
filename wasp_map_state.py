"""Persistence and edit operations for the W.A.S.P. live war map.

The map is a satellite view of the real world on which admins stage a
fictional war: factions, unit positions, controlled zones, front lines and a
running SITREP feed.  Everything is stored as one JSON document.  Admin edits
arrive as small operations (``upsert`` one unit, ``delete`` one zone, ...)
that are applied server side against the latest stored copy, so two admins
editing at the same time do not overwrite each other's work.
"""

from __future__ import annotations

import math
import re
import secrets
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from constants import ROOT_PREFIX
from storage_spaces import read_json, write_json

SCHEMA_VERSION = 2

_WASP_STATE_FILENAME = "operations/wasp-war-map.json"
WASP_MAP_STATE_PATH = (
    f"{ROOT_PREFIX}/{_WASP_STATE_FILENAME}" if ROOT_PREFIX else _WASP_STATE_FILENAME
)

UNIT_TYPES = (
    "infantry",
    "mechanized",
    "armor",
    "artillery",
    "air_defense",
    "air",
    "helicopter",
    "drone",
    "naval",
    "submarine",
    "missile",
    "recon",
    "special_forces",
    "hq",
    "logistics",
)
UNIT_ECHELONS = ("", "company", "battalion", "brigade", "division", "corps", "army")
UNIT_STATUSES = ("active", "engaged", "damaged", "retreating", "destroyed")
FACTION_STANCES = ("friendly", "hostile", "neutral", "unknown")
ZONE_KINDS = ("control", "contested", "exclusion", "objective")
LINE_KINDS = ("front", "advance", "supply", "border")
EVENT_KINDS = ("battle", "strike", "movement", "intel", "political", "report")
WAR_STATUSES = ("standby", "active", "ceasefire", "concluded")

COLLECTIONS = ("factions", "units", "zones", "lines", "events")

MAX_FACTIONS = 12
MAX_UNITS = 600
MAX_ZONES = 250
MAX_LINES = 250
MAX_EVENTS = 200
MAX_SHAPE_POINTS = 400
MAX_OPS_PER_REQUEST = 50

_COLLECTION_LIMITS = {
    "factions": MAX_FACTIONS,
    "units": MAX_UNITS,
    "zones": MAX_ZONES,
    "lines": MAX_LINES,
    "events": MAX_EVENTS,
}
_ID_PREFIX = {"factions": "f", "units": "u", "zones": "z", "lines": "l", "events": "e"}

_DEFAULT_FACTIONS = [
    {"id": "coalition", "name": "Allied Coalition", "short": "COAL", "color": "#3b82f6", "stance": "friendly"},
    {"id": "hostile", "name": "Hostile Forces", "short": "HOST", "color": "#ef4444", "stance": "hostile"},
    {"id": "neutral", "name": "Neutral Parties", "short": "NEUT", "color": "#22c55e", "stance": "neutral"},
]

_ID_PATTERN = re.compile(r"[^A-Za-z0-9_-]")
_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Viewers poll the state every few seconds; a short in-process cache keeps
# that from turning into one storage read per viewer per poll.
_READ_CACHE_TTL_SECONDS = 2.0
_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"state": None, "etag": None, "at": 0.0}


class WaspMapOpError(ValueError):
    """Raised when an edit operation is malformed."""


class WaspMapConflictError(RuntimeError):
    """Raised when the state kept changing underneath an update."""


# ---------------------------------------------------------------------------
# Normalisers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _text(value: Any, fallback: str = "", *, limit: int = 80, multiline: bool = False) -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = _CONTROL_CHARS.sub("", value)
    if not multiline:
        cleaned = " ".join(cleaned.split())
    cleaned = cleaned.strip()[:limit].strip()
    return cleaned or fallback


def _choice(value: Any, allowed: Iterable[str], fallback: str) -> str:
    candidate = value.strip().lower() if isinstance(value, str) else ""
    return candidate if candidate in allowed else fallback


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _int(value: Any, fallback: int, low: int, high: int) -> int:
    number = _number(value)
    if number is None:
        return fallback
    return max(low, min(high, int(round(number))))


def _lat(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return round(max(-85.0, min(85.0, number)), 5)


def _lng(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    wrapped = ((number + 180.0) % 360.0) - 180.0
    if wrapped == -180.0 and number > 0:
        wrapped = 180.0
    return round(wrapped, 5)


def _identifier(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return _ID_PATTERN.sub("", value.strip())[:40]


def new_id(collection: str) -> str:
    return f"{_ID_PREFIX.get(collection, 'x')}-{secrets.token_hex(5)}"


def _timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()[:40]
    if not cleaned:
        return None
    try:
        datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return None
    return cleaned


def _points(value: Any, minimum: int) -> list[list[float]] | None:
    if not isinstance(value, list):
        return None
    points: list[list[float]] = []
    for raw in value[:MAX_SHAPE_POINTS]:
        lat = lng = None
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            lat, lng = _lat(raw[0]), _lng(raw[1])
        elif isinstance(raw, Mapping):
            lat, lng = _lat(raw.get("lat")), _lng(raw.get("lng"))
        if lat is None or lng is None:
            continue
        points.append([lat, lng])
    return points if len(points) >= minimum else None


# ---------------------------------------------------------------------------
# Item sanitisers (return ``None`` when an item is unusable)
# ---------------------------------------------------------------------------


def _sanitize_faction(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    faction_id = _identifier(entry.get("id"))
    if not faction_id:
        return None
    name = _text(entry.get("name"), "Unnamed Faction", limit=48)
    short = _text(entry.get("short"), name[:4], limit=6).upper()
    color = entry.get("color")
    if not isinstance(color, str) or not _COLOR_PATTERN.match(color.strip()):
        color = "#9ca3af"
    return {
        "id": faction_id,
        "name": name,
        "short": short,
        "color": color.strip().lower(),
        "stance": _choice(entry.get("stance"), FACTION_STANCES, "unknown"),
    }


def _sanitize_unit(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    unit_id = _identifier(entry.get("id"))
    lat, lng = _lat(entry.get("lat")), _lng(entry.get("lng"))
    if not unit_id or lat is None or lng is None:
        return None
    return {
        "id": unit_id,
        "name": _text(entry.get("name"), "Unnamed Unit", limit=60),
        "faction": _identifier(entry.get("faction")),
        "type": _choice(entry.get("type"), UNIT_TYPES, "infantry"),
        "echelon": _choice(entry.get("echelon"), UNIT_ECHELONS, ""),
        "status": _choice(entry.get("status"), UNIT_STATUSES, "active"),
        "strength": _int(entry.get("strength"), 100, 0, 100),
        "lat": lat,
        "lng": lng,
        "notes": _text(entry.get("notes"), "", limit=600, multiline=True),
    }


def _sanitize_zone(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    zone_id = _identifier(entry.get("id"))
    points = _points(entry.get("points"), 3)
    if not zone_id or points is None:
        return None
    return {
        "id": zone_id,
        "name": _text(entry.get("name"), "Unnamed Zone", limit=60),
        "faction": _identifier(entry.get("faction")),
        "kind": _choice(entry.get("kind"), ZONE_KINDS, "control"),
        "points": points,
        "notes": _text(entry.get("notes"), "", limit=600, multiline=True),
    }


def _sanitize_line(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    line_id = _identifier(entry.get("id"))
    points = _points(entry.get("points"), 2)
    if not line_id or points is None:
        return None
    return {
        "id": line_id,
        "name": _text(entry.get("name"), "Unnamed Line", limit=60),
        "faction": _identifier(entry.get("faction")),
        "kind": _choice(entry.get("kind"), LINE_KINDS, "front"),
        "points": points,
        "notes": _text(entry.get("notes"), "", limit=600, multiline=True),
    }


def _sanitize_event(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    event_id = _identifier(entry.get("id"))
    if not event_id:
        return None
    lat, lng = _lat(entry.get("lat")), _lng(entry.get("lng"))
    if lat is None or lng is None:
        lat = lng = None
    return {
        "id": event_id,
        "kind": _choice(entry.get("kind"), EVENT_KINDS, "report"),
        "title": _text(entry.get("title"), "Situation report", limit=90),
        "body": _text(entry.get("body"), "", limit=1200, multiline=True),
        "lat": lat,
        "lng": lng,
        "ts": _timestamp(entry.get("ts")) or _now_iso(),
        "author": _text(entry.get("author"), "", limit=48),
    }


_SANITIZERS = {
    "factions": _sanitize_faction,
    "units": _sanitize_unit,
    "zones": _sanitize_zone,
    "lines": _sanitize_line,
    "events": _sanitize_event,
}


def _sanitize_view(value: Any) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    lat, lng = _lat(value.get("lat")), _lng(value.get("lng"))
    zoom = _number(value.get("zoom"))
    if lat is None or lng is None or zoom is None:
        return None
    return {"lat": lat, "lng": lng, "zoom": round(max(1.0, min(18.0, zoom)), 2)}


def _sanitize_meta(value: Any) -> dict[str, Any]:
    payload = value if isinstance(value, Mapping) else {}
    war_start = payload.get("warStart")
    if not isinstance(war_start, str) or not _DATE_PATTERN.match(war_start.strip()):
        war_start = ""
    return {
        "operation": _text(payload.get("operation"), "Unnamed Operation", limit=60),
        "theatre": _text(payload.get("theatre"), "", limit=60),
        "summary": _text(payload.get("summary"), "", limit=600, multiline=True),
        "status": _choice(payload.get("status"), WAR_STATUSES, "standby"),
        "threatLevel": _int(payload.get("threatLevel"), 3, 1, 5),
        "warStart": war_start.strip(),
        "view": _sanitize_view(payload.get("view")),
    }


def _sanitize_collection(name: str, value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    sanitizer = _SANITIZERS[name]
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        item = sanitizer(raw)
        if item is None or item["id"] in seen:
            continue
        seen.add(item["id"])
        items.append(item)
    if name == "events":
        items.sort(key=lambda item: item["ts"], reverse=True)
    return items[: _COLLECTION_LIMITS[name]]


def default_wasp_map_state() -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "revision": 0,
        "updatedAt": None,
        "updatedBy": "",
        "meta": _sanitize_meta({}),
        "factions": deepcopy(_DEFAULT_FACTIONS),
        "units": [],
        "zones": [],
        "lines": [],
        "events": [],
    }


def sanitize_wasp_map_state(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a clean, complete state document built from ``payload``."""

    if not isinstance(payload, Mapping) or payload.get("schema") != SCHEMA_VERSION:
        # Anything that is not a v2 document (including the retired 3D map's
        # x/z unit layout) starts from a clean theatre.
        return default_wasp_map_state()

    state = {
        "schema": SCHEMA_VERSION,
        "revision": _int(payload.get("revision"), 0, 0, 2**31 - 1),
        "updatedAt": _timestamp(payload.get("updatedAt")),
        "updatedBy": _text(payload.get("updatedBy"), "", limit=48),
        "meta": _sanitize_meta(payload.get("meta")),
    }
    for name in COLLECTIONS:
        state[name] = _sanitize_collection(name, payload.get(name))
    if not state["factions"]:
        state["factions"] = deepcopy(_DEFAULT_FACTIONS)
    return state


# ---------------------------------------------------------------------------
# Edit operations
# ---------------------------------------------------------------------------


def _collection_arg(op: Mapping[str, Any]) -> str:
    collection = op.get("collection")
    if collection not in COLLECTIONS:
        raise WaspMapOpError(f"Unknown collection: {collection!r}")
    return str(collection)


def _apply_upsert(state: dict[str, Any], op: Mapping[str, Any], actor: str) -> None:
    collection = _collection_arg(op)
    patch = op.get("item")
    if not isinstance(patch, Mapping):
        raise WaspMapOpError("upsert requires an 'item' object")
    items: list[dict[str, Any]] = state[collection]
    item_id = _identifier(patch.get("id"))
    index = next((i for i, item in enumerate(items) if item["id"] == item_id), None) if item_id else None

    if index is None:
        if len(items) >= _COLLECTION_LIMITS[collection]:
            if collection != "events":
                raise WaspMapOpError(f"The map already holds the maximum number of {collection}.")
            items.pop()  # events: drop the oldest entry
        merged = dict(patch)
        merged["id"] = item_id or new_id(collection)
        if collection == "events":
            merged.setdefault("author", actor)
            if not _timestamp(merged.get("ts")):
                merged["ts"] = _now_iso()
    else:
        merged = {**items[index], **patch, "id": item_id}

    clean = _SANITIZERS[collection](merged)
    if clean is None:
        raise WaspMapOpError(f"Invalid {collection[:-1]} data (check name and coordinates).")

    if index is None:
        items.append(clean)
    else:
        items[index] = clean
    if collection == "events":
        items.sort(key=lambda item: item["ts"], reverse=True)


def _apply_delete(state: dict[str, Any], op: Mapping[str, Any]) -> None:
    collection = _collection_arg(op)
    item_id = _identifier(op.get("id"))
    if not item_id:
        raise WaspMapOpError("delete requires an 'id'")
    state[collection] = [item for item in state[collection] if item["id"] != item_id]
    if collection == "factions" and not state["factions"]:
        raise WaspMapOpError("The map needs at least one faction.")


def _apply_meta(state: dict[str, Any], op: Mapping[str, Any]) -> None:
    patch = op.get("patch")
    if not isinstance(patch, Mapping):
        raise WaspMapOpError("meta requires a 'patch' object")
    state["meta"] = _sanitize_meta({**state["meta"], **patch})


def _apply_clear(state: dict[str, Any], op: Mapping[str, Any]) -> None:
    collection = _collection_arg(op)
    if collection == "factions":
        raise WaspMapOpError("Factions cannot be cleared; delete them one at a time.")
    state[collection] = []


def _apply_replace(state: dict[str, Any], op: Mapping[str, Any]) -> dict[str, Any]:
    incoming = op.get("state")
    if not isinstance(incoming, Mapping):
        raise WaspMapOpError("replace requires a 'state' object")
    replacement = sanitize_wasp_map_state({**incoming, "schema": SCHEMA_VERSION})
    replacement["revision"] = state["revision"]
    return replacement


def apply_wasp_map_ops(
    state: Mapping[str, Any],
    ops: Any,
    *,
    actor: str = "",
) -> dict[str, Any]:
    """Apply edit operations to a copy of ``state`` and return the result."""

    if not isinstance(ops, list) or not ops:
        raise WaspMapOpError("Send a non-empty 'ops' list.")
    if len(ops) > MAX_OPS_PER_REQUEST:
        raise WaspMapOpError(f"Send at most {MAX_OPS_PER_REQUEST} operations at once.")

    next_state = sanitize_wasp_map_state(deepcopy(dict(state)))
    for op in ops:
        if not isinstance(op, Mapping):
            raise WaspMapOpError("Each operation must be an object.")
        kind = op.get("op")
        if kind == "upsert":
            _apply_upsert(next_state, op, actor)
        elif kind == "delete":
            _apply_delete(next_state, op)
        elif kind == "meta":
            _apply_meta(next_state, op)
        elif kind == "clear":
            _apply_clear(next_state, op)
        elif kind == "replace":
            next_state = _apply_replace(next_state, op)
        else:
            raise WaspMapOpError(f"Unknown operation: {kind!r}")

    next_state["revision"] = int(next_state.get("revision") or 0) + 1
    next_state["updatedAt"] = _now_iso()
    next_state["updatedBy"] = _text(actor, "", limit=48)
    return next_state


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def _remember(state: dict[str, Any] | None, etag: str | None) -> None:
    with _cache_lock:
        _cache["state"] = state
        _cache["etag"] = etag
        _cache["at"] = time.monotonic() if state is not None else 0.0


def clear_wasp_map_cache() -> None:
    _remember(None, None)


def load_wasp_map_state(*, with_etag: bool = False, use_cache: bool = True):
    state: dict[str, Any] | None = None
    etag: str | None = None
    if use_cache:
        with _cache_lock:
            if _cache["state"] is not None and time.monotonic() - _cache["at"] < _READ_CACHE_TTL_SECONDS:
                state, etag = deepcopy(_cache["state"]), _cache["etag"]
    if state is None:
        data, etag = read_json(WASP_MAP_STATE_PATH, with_etag=True)
        state = sanitize_wasp_map_state(data)
        _remember(deepcopy(state), etag)
    if with_etag:
        return state, etag
    return state


def update_wasp_map_state(ops: Any, *, actor: str = "", attempts: int = 5):
    """Apply ``ops`` to the stored state, retrying on concurrent writes.

    Returns ``(state, etag)`` after the write.  Raises ``WaspMapOpError`` for
    bad operations and ``WaspMapConflictError`` if every attempt raced
    another writer.
    """

    for _ in range(max(1, attempts)):
        current, etag = load_wasp_map_state(with_etag=True, use_cache=False)
        next_state = apply_wasp_map_ops(current, ops, actor=actor)
        if write_json(WASP_MAP_STATE_PATH, next_state, etag=etag):
            clear_wasp_map_cache()
            return load_wasp_map_state(with_etag=True, use_cache=False)
    clear_wasp_map_cache()
    raise WaspMapConflictError("The map changed too many times in a row; try again.")
