"""Guild-scoped persistence for W.A.S.P tactical planning data."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from constants import ROOT_PREFIX
from storage_spaces import read_json, write_json

_ALLOWED_PHASES = {"recon", "engagement", "extraction", "afteraction"}
_MAX_ROUTES = 200
_MAX_ZONES = 200
_MAX_ANNOTATIONS = 400


def _normalize_text(value: Any, fallback: str = "") -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = value.strip()
    return cleaned or fallback


def _normalize_number(value: Any, fallback: float = 0.0) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return fallback
    if normalized != normalized:  # NaN guard
        return fallback
    return normalized


def _sanitize_points(entries: Any, *, max_items: int = 120) -> list[dict[str, float]]:
    if not isinstance(entries, list):
        return []
    points: list[dict[str, float]] = []
    for item in entries[:max_items]:
        if not isinstance(item, Mapping):
            continue
        points.append(
            {
                "x": round(_normalize_number(item.get("x"), 0.0), 3),
                "z": round(_normalize_number(item.get("z"), 0.0), 3),
            }
        )
    return points


def default_wasp_planning_state() -> dict[str, Any]:
    return {
        "version": 1,
        "phase": "recon",
        "routes": [],
        "zones": [],
        "annotations": [],
    }


def sanitize_wasp_planning_state(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return default_wasp_planning_state()

    phase = _normalize_text(payload.get("phase"), "recon").lower()
    if phase not in _ALLOWED_PHASES:
        phase = "recon"

    routes_raw = payload.get("routes")
    routes: list[dict[str, Any]] = []
    if isinstance(routes_raw, list):
        for index, route in enumerate(routes_raw[:_MAX_ROUTES]):
            if not isinstance(route, Mapping):
                continue
            waypoints = _sanitize_points(route.get("waypoints"), max_items=120)
            if len(waypoints) < 2:
                continue
            routes.append(
                {
                    "id": _normalize_text(route.get("id"), f"route-{index + 1}"),
                    "label": _normalize_text(route.get("label"), f"Route {index + 1}"),
                    "waypoints": waypoints,
                }
            )

    zones_raw = payload.get("zones")
    zones: list[dict[str, Any]] = []
    if isinstance(zones_raw, list):
        for index, zone in enumerate(zones_raw[:_MAX_ZONES]):
            if not isinstance(zone, Mapping):
                continue
            points = _sanitize_points(zone.get("points"), max_items=120)
            if len(points) < 3:
                continue
            zones.append(
                {
                    "id": _normalize_text(zone.get("id"), f"zone-{index + 1}"),
                    "label": _normalize_text(zone.get("label"), f"Zone {index + 1}"),
                    "threatType": _normalize_text(zone.get("threatType"), "unknown"),
                    "status": _normalize_text(zone.get("status"), "active"),
                    "points": points,
                }
            )

    annotations_raw = payload.get("annotations")
    annotations: list[dict[str, Any]] = []
    if isinstance(annotations_raw, list):
        for index, annotation in enumerate(annotations_raw[:_MAX_ANNOTATIONS]):
            if not isinstance(annotation, Mapping):
                continue
            priority = int(_normalize_number(annotation.get("priority"), 3))
            annotations.append(
                {
                    "id": _normalize_text(annotation.get("id"), f"annotation-{index + 1}"),
                    "title": _normalize_text(annotation.get("title"), "NOTE"),
                    "note": _normalize_text(annotation.get("note"), ""),
                    "priority": max(1, min(5, priority)),
                    "x": round(_normalize_number(annotation.get("x"), 0.0), 3),
                    "z": round(_normalize_number(annotation.get("z"), 0.0), 3),
                }
            )

    version = int(_normalize_number(payload.get("version"), 1))
    return {
        "version": max(1, version),
        "phase": phase,
        "routes": routes,
        "zones": zones,
        "annotations": annotations,
    }


def _planning_state_path(guild_id: str) -> str:
    cleaned = "".join(ch for ch in str(guild_id).strip() if ch.isdigit()) or "0"
    filename = f"operations/wasp-planning/{cleaned}.json"
    return f"{ROOT_PREFIX}/{filename}" if ROOT_PREFIX else filename


def load_wasp_planning_state(guild_id: str, *, with_etag: bool = False):
    path = _planning_state_path(guild_id)
    data, etag = read_json(path, with_etag=True)
    state = sanitize_wasp_planning_state(data)
    if with_etag:
        return deepcopy(state), etag
    return deepcopy(state)


def save_wasp_planning_state(
    guild_id: str,
    payload: Mapping[str, Any] | None,
    *,
    etag: str | None = None,
) -> bool:
    path = _planning_state_path(guild_id)
    state = sanitize_wasp_planning_state(payload)
    return write_json(path, state, etag=etag)
