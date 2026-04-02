"""Persistence helpers for the shared W.A.S.P. tactical map state."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from constants import ROOT_PREFIX
from storage_spaces import read_json, write_json

_WASP_STATE_FILENAME = "operations/wasp-map-state.json"
WASP_MAP_STATE_PATH = (
    f"{ROOT_PREFIX}/{_WASP_STATE_FILENAME}" if ROOT_PREFIX else _WASP_STATE_FILENAME
)

_DEFAULT_UNITS = [
    {
        "id": "seed-falcon-1",
        "type": "aircraft",
        "name": "Falcon-1",
        "country": "USA",
        "side": "friendly",
        "x": 30,
        "z": 10,
    },
    {
        "id": "seed-t-90",
        "type": "tank",
        "name": "T-90",
        "country": "Russia",
        "side": "enemy",
        "x": -20,
        "z": 25,
    },
    {
        "id": "seed-sentinel-2",
        "type": "infantry",
        "name": "Sentinel-2",
        "country": "UN",
        "side": "neutral",
        "x": 0,
        "z": 0,
    },
]

_ALLOWED_SIDES = {"enemy", "friendly", "neutral", "objective"}
_ALLOWED_RUNNER_STATUS = {"idle", "running", "paused"}
_ALLOWED_MISSION_STATUS = {"queued", "active", "completed", "aborted"}
_ALLOWED_ENGAGEMENT_OUTCOME = {"pending", "hit", "kill", "miss", "aborted"}
_MAX_EVENTS = 400
_MAX_MISSIONS = 250
_MAX_ENGAGEMENTS = 400


def _normalize_text(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = value.strip()
    return cleaned or fallback


def _normalize_number(value: Any, fallback: float = 0.0) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return fallback
    if normalized != normalized:  # NaN
        return fallback
    return normalized


def _sanitize_unit(entry: Mapping[str, Any], index: int) -> dict[str, Any]:
    side = _normalize_text(entry.get("side"), "enemy").lower()
    if side not in _ALLOWED_SIDES:
        side = "enemy"

    unit_id = _normalize_text(entry.get("id"), f"unit-{index + 1}")
    return {
        "id": unit_id,
        "type": _normalize_text(entry.get("type"), "unknown").lower(),
        "name": _normalize_text(entry.get("name"), "Unknown"),
        "country": _normalize_text(entry.get("country"), "Unknown"),
        "side": side,
        "x": _normalize_number(entry.get("x"), 0.0),
        "z": _normalize_number(entry.get("z"), 0.0),
    }


def _normalize_int(value: Any, fallback: int = 0) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return fallback
    return normalized


def _normalize_timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _sanitize_runner(entry: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = entry if isinstance(entry, Mapping) else {}
    status = _normalize_text(payload.get("status"), "idle").lower()
    if status not in _ALLOWED_RUNNER_STATUS:
        status = "idle"
    tick = max(0, _normalize_int(payload.get("tick"), 0))
    speed = _normalize_number(payload.get("speed"), 1.0)
    if speed <= 0:
        speed = 1.0
    return {
        "status": status,
        "tick": tick,
        "speed": round(min(speed, 25.0), 3),
        "startedBy": _normalize_text(payload.get("startedBy"), ""),
        "startedAt": _normalize_timestamp(payload.get("startedAt")),
        "updatedAt": _normalize_timestamp(payload.get("updatedAt")),
        "seed": max(0, _normalize_int(payload.get("seed"), 1)),
    }


def _sanitize_mission(entry: Mapping[str, Any], index: int) -> dict[str, Any]:
    mission_id = _normalize_text(entry.get("id"), f"mission-{index + 1}")
    status = _normalize_text(entry.get("status"), "queued").lower()
    if status not in _ALLOWED_MISSION_STATUS:
        status = "queued"
    return {
        "id": mission_id,
        "attackerId": _normalize_text(entry.get("attackerId"), ""),
        "targetId": _normalize_text(entry.get("targetId"), ""),
        "weaponType": _normalize_text(entry.get("weaponType"), "missile").lower(),
        "priority": max(1, min(10, _normalize_int(entry.get("priority"), 5))),
        "status": status,
        "createdAt": _normalize_timestamp(entry.get("createdAt")),
        "startedAt": _normalize_timestamp(entry.get("startedAt")),
        "resolvedAt": _normalize_timestamp(entry.get("resolvedAt")),
        "lastProgress": round(max(0.0, min(1.0, _normalize_number(entry.get("lastProgress"), 0.0))), 4),
        "notes": _normalize_text(entry.get("notes"), ""),
    }


def _sanitize_engagement(entry: Mapping[str, Any], index: int) -> dict[str, Any]:
    engagement_id = _normalize_text(entry.get("id"), f"engagement-{index + 1}")
    outcome = _normalize_text(entry.get("outcome"), "pending").lower()
    if outcome not in _ALLOWED_ENGAGEMENT_OUTCOME:
        outcome = "pending"
    return {
        "id": engagement_id,
        "missionId": _normalize_text(entry.get("missionId"), ""),
        "attackerId": _normalize_text(entry.get("attackerId"), ""),
        "targetId": _normalize_text(entry.get("targetId"), ""),
        "tickStarted": max(0, _normalize_int(entry.get("tickStarted"), 0)),
        "tickResolved": max(0, _normalize_int(entry.get("tickResolved"), 0)),
        "outcome": outcome,
        "damage": max(0, min(100, _normalize_int(entry.get("damage"), 0))),
    }


def _sanitize_event(entry: Mapping[str, Any], index: int) -> dict[str, Any]:
    event_id = _normalize_text(entry.get("id"), f"event-{index + 1}")
    return {
        "id": event_id,
        "tick": max(0, _normalize_int(entry.get("tick"), 0)),
        "type": _normalize_text(entry.get("type"), "log").lower(),
        "message": _normalize_text(entry.get("message"), ""),
        "missionId": _normalize_text(entry.get("missionId"), ""),
        "attackerId": _normalize_text(entry.get("attackerId"), ""),
        "targetId": _normalize_text(entry.get("targetId"), ""),
        "createdAt": _normalize_timestamp(entry.get("createdAt")),
    }


def default_wasp_map_state() -> dict[str, Any]:
    return {
        "units": deepcopy(_DEFAULT_UNITS),
        "missions": [],
        "engagements": [],
        "runner": _sanitize_runner({}),
        "events": [],
    }


def sanitize_wasp_map_state(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return default_wasp_map_state()

    units_payload = payload.get("units")
    units: list[dict[str, Any]] = []
    if isinstance(units_payload, list):
        for index, raw_entry in enumerate(units_payload):
            if not isinstance(raw_entry, Mapping):
                continue
            units.append(_sanitize_unit(raw_entry, index))

    missions_payload = payload.get("missions")
    missions: list[dict[str, Any]] = []
    if isinstance(missions_payload, list):
        for index, raw_entry in enumerate(missions_payload[:_MAX_MISSIONS]):
            if not isinstance(raw_entry, Mapping):
                continue
            missions.append(_sanitize_mission(raw_entry, index))

    engagements_payload = payload.get("engagements")
    engagements: list[dict[str, Any]] = []
    if isinstance(engagements_payload, list):
        for index, raw_entry in enumerate(engagements_payload[:_MAX_ENGAGEMENTS]):
            if not isinstance(raw_entry, Mapping):
                continue
            engagements.append(_sanitize_engagement(raw_entry, index))

    events_payload = payload.get("events")
    events: list[dict[str, Any]] = []
    if isinstance(events_payload, list):
        for index, raw_entry in enumerate(events_payload[:_MAX_EVENTS]):
            if not isinstance(raw_entry, Mapping):
                continue
            events.append(_sanitize_event(raw_entry, index))

    runner = _sanitize_runner(payload.get("runner"))

    if not units:
        default_state = default_wasp_map_state()
        default_state["missions"] = missions
        default_state["engagements"] = engagements
        default_state["runner"] = runner
        default_state["events"] = events
        return default_state

    return {
        "units": units,
        "missions": missions,
        "engagements": engagements,
        "runner": runner,
        "events": events,
    }


def load_wasp_map_state(*, with_etag: bool = False):
    data, etag = read_json(WASP_MAP_STATE_PATH, with_etag=True)
    state = sanitize_wasp_map_state(data)
    if with_etag:
        return state, etag
    return state


def save_wasp_map_state(payload: Mapping[str, Any] | None, *, etag: str | None = None) -> bool:
    state = sanitize_wasp_map_state(payload)
    return write_json(WASP_MAP_STATE_PATH, state, etag=etag)
