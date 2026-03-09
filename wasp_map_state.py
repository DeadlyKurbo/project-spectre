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


def default_wasp_map_state() -> dict[str, Any]:
    return {
        "units": deepcopy(_DEFAULT_UNITS),
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

    if not units:
        return default_wasp_map_state()

    return {"units": units}


def load_wasp_map_state(*, with_etag: bool = False):
    data, etag = read_json(WASP_MAP_STATE_PATH, with_etag=True)
    state = sanitize_wasp_map_state(data)
    if with_etag:
        return state, etag
    return state


def save_wasp_map_state(payload: Mapping[str, Any] | None, *, etag: str | None = None) -> bool:
    state = sanitize_wasp_map_state(payload)
    return write_json(WASP_MAP_STATE_PATH, state, etag=etag)
