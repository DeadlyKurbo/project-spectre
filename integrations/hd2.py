from __future__ import annotations

import asyncio
import math
import os
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

__all__ = ["get_hd2_summary", "HelldiversIntegrationError"]


def _resolve_cache_ttl() -> float:
    raw = os.getenv("HD2_CACHE_TTL", "60")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 60.0
    return value if value >= 0 else 60.0


HD2_API_BASE = "https://helldiverstrainingmanual.com/api/v1/war"
HD2_CACHE_TTL_SECONDS = _resolve_cache_ttl()
_REQUEST_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_DEFAULT_HEADERS = {
    "User-Agent": "SpectreDashboard/HelldiversII (+https://helldiverstrainingmanual.com)",
    "Accept": "application/json",
}


class HelldiversIntegrationError(RuntimeError):
    """Raised when Helldivers II data cannot be retrieved."""


_hd2_cache: dict[str, Any] = {"data": None, "ts": 0.0}
_hd2_lock = asyncio.Lock()


async def get_hd2_summary(force_refresh: bool = False) -> dict[str, Any]:
    """Return a cached summary of the Helldivers II Galactic War."""

    now = time.time()
    async with _hd2_lock:
        cached = _hd2_cache.get("data")
        cached_ts = float(_hd2_cache.get("ts") or 0.0)
        if not force_refresh and cached and now - cached_ts < HD2_CACHE_TTL_SECONDS:
            return cached

    campaign_data, major_orders, news_data = await _fetch_hd2_payloads()
    summary = _build_summary(campaign_data, major_orders, news_data)

    async with _hd2_lock:
        _hd2_cache["data"] = summary
        _hd2_cache["ts"] = time.time()
    return summary


async def _fetch_hd2_payloads() -> tuple[Any, Any, Any]:
    try:
        async with httpx.AsyncClient(
            base_url=HD2_API_BASE,
            headers=_DEFAULT_HEADERS,
            timeout=_REQUEST_TIMEOUT,
        ) as client:
            responses = await asyncio.gather(
                _request_json(client, "campaign"),
                _request_json(client, "major-orders"),
                _request_json(client, "news"),
            )
    except HelldiversIntegrationError:
        raise
    except httpx.TimeoutException as exc:
        raise HelldiversIntegrationError("Timed out contacting the Helldivers data feed.") from exc
    except httpx.HTTPError as exc:
        raise HelldiversIntegrationError("Failed to contact the Helldivers data feed.") from exc
    return responses  # type: ignore[return-value]


async def _request_json(client: httpx.AsyncClient, path: str) -> Any:
    try:
        response = await client.get(path)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        detail = exc.response.text.strip() if exc.response.text else ""
        message = f"Helldivers API responded with {status} for {path}"
        if detail:
            message = f"{message}: {detail}"
        raise HelldiversIntegrationError(message) from exc
    except httpx.TimeoutException as exc:
        raise HelldiversIntegrationError("Timed out waiting for Helldivers API response.") from exc
    except httpx.HTTPError as exc:
        raise HelldiversIntegrationError("Unexpected error contacting Helldivers API.") from exc
    try:
        return response.json()
    except ValueError as exc:
        raise HelldiversIntegrationError("Helldivers API returned invalid JSON.") from exc


def _build_summary(campaign_data: Any, major_orders_data: Any, news_data: Any) -> dict[str, Any]:
    now = time.time()
    planets = [_normalise_planet(entry, now) for entry in _iter_planets(campaign_data)]
    planets = [planet for planet in planets if planet]

    def _planet_score(item: dict[str, Any]) -> tuple[float, float]:
        progress = _coerce_float(item.get("liberation"))
        priority = _coerce_float(item.get("priority")) or 0.0
        return (progress if progress is not None else -1.0, priority)

    hottest_planets = sorted(planets, key=_planet_score, reverse=True)[:5]

    summary: dict[str, Any] = {
        "hottest_planets": hottest_planets,
        "major_order": _normalise_major_order(major_orders_data, now),
        "news": _normalise_news(news_data),
        "war_snapshot": _build_war_snapshot(planets),
        "updated_at": now,
    }
    return summary


def _iter_planets(payload: Any) -> list[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        return []

    seen_ids: set[Any] = set()
    planets: list[Mapping[str, Any]] = []

    for key in ("campaigns", "planets", "planet_status", "planetStatus", "fronts"):
        entries = payload.get(key)
        if isinstance(entries, Sequence):
            for entry in entries:
                if isinstance(entry, Mapping):
                    planet_id = _extract_planet_identifier(entry)
                    if planet_id in seen_ids:
                        continue
                    if planet_id is not None:
                        seen_ids.add(planet_id)
                    planets.append(entry)

    return planets


def _extract_planet_identifier(entry: Mapping[str, Any]) -> Any:
    planet = entry.get("planet")
    if isinstance(planet, Mapping):
        identifier = planet.get("id") or planet.get("index") or planet.get("name")
        if identifier is not None:
            return identifier
    return entry.get("id") or entry.get("planet_id") or entry.get("name")


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isnan(value):
            return None
        return float(value)
    try:
        stripped = str(value).strip()
    except Exception:
        return None
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


def _coerce_percent(*candidates: Any) -> float | None:
    for candidate in candidates:
        value = _coerce_float(candidate)
        if value is None:
            continue
        if 0 <= value <= 1:
            value *= 100
        if value < 0:
            continue
        return min(100.0, value)
    return None


def _normalise_planet(entry: Mapping[str, Any], now: float) -> dict[str, Any]:
    planet_info = entry.get("planet") if isinstance(entry.get("planet"), Mapping) else {}
    if not isinstance(planet_info, Mapping):
        planet_info = {}

    name = _first_non_empty(
        planet_info.get("name"),
        entry.get("planet_name"),
        entry.get("name"),
    ) or "Unknown planet"

    enemy_info = entry.get("enemy") if isinstance(entry.get("enemy"), Mapping) else {}
    enemy = _first_non_empty(
        enemy_info.get("name"),
        enemy_info.get("type"),
        entry.get("enemy"),
        entry.get("enemy_type"),
        planet_info.get("enemy"),
    )

    mission_label = _first_non_empty(
        entry.get("mission_type"),
        entry.get("type"),
        entry.get("mission"),
        entry.get("operation_type"),
        planet_info.get("mission_type"),
        planet_info.get("type"),
    )
    mission_type: str | None
    if isinstance(mission_label, Mapping):
        mission_label = mission_label.get("name") or mission_label.get("type")
    if mission_label is not None:
        mission_type = str(mission_label).strip().lower() or None
        mission_label = str(mission_label).strip()
    else:
        mission_type = None

    progress = _coerce_percent(
        entry.get("liberation"),
        entry.get("liberation_percent"),
        entry.get("liberationPercent"),
        entry.get("progress"),
        entry.get("percentage"),
        planet_info.get("liberation"),
        planet_info.get("progress"),
    )

    current = _coerce_float(entry.get("current"))
    target = _coerce_float(entry.get("target")) or _coerce_float(entry.get("required"))
    if progress is None and current is not None and target:
        progress = min(100.0, (current / target) * 100) if target else None

    status = _first_non_empty(
        entry.get("status"),
        entry.get("state"),
        planet_info.get("state"),
        planet_info.get("status"),
    )

    expires_at = _parse_timestamp(
        entry.get("expires_at"),
        entry.get("expiresAt"),
        entry.get("expiry"),
        entry.get("end_time"),
        entry.get("endTime"),
    )
    if expires_at is None and isinstance(planet_info, Mapping):
        expires_at = _parse_timestamp(
            planet_info.get("expires_at"),
            planet_info.get("end_time"),
        )
    time_remaining = expires_at - now if expires_at else None
    if time_remaining is not None and time_remaining < 0:
        time_remaining = 0

    priority = _coerce_float(entry.get("priority")) or _coerce_float(planet_info.get("priority")) or 0.0

    return {
        "id": _extract_planet_identifier(entry),
        "name": name,
        "enemy": enemy,
        "mission_type": mission_type,
        "mission_label": mission_label,
        "liberation": progress,
        "status": status,
        "time_remaining": time_remaining,
        "expires_at": expires_at,
        "priority": priority,
    }


def _parse_timestamp(*candidates: Any) -> float | None:
    for candidate in candidates:
        if candidate is None:
            continue
        if isinstance(candidate, (int, float)):
            return float(candidate)
        if isinstance(candidate, str):
            text = candidate.strip()
            if not text:
                continue
            for transform in (_parse_isoformat, _parse_http_date):
                dt = transform(text)
                if dt is not None:
                    return dt
    return None


def _parse_isoformat(value: str) -> float | None:
    try:
        cleaned = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _parse_http_date(value: str) -> float | None:
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned
        elif value:
            return value
    return None


def _normalise_major_order(payload: Any, now: float) -> dict[str, Any] | None:
    candidates = _extract_major_orders(payload)
    if not candidates:
        return None

    def _order_sort_key(order: Mapping[str, Any]) -> tuple[float, float]:
        expires = _parse_timestamp(
            order.get("expires_at"),
            order.get("expiresAt"),
            order.get("expiry"),
            order.get("end_time"),
        )
        return (0 if _is_order_active(order, now) else 1, -(expires or 0))

    selected = sorted(candidates, key=_order_sort_key)[0]

    expires_at = _parse_timestamp(
        selected.get("expires_at"),
        selected.get("expiresAt"),
        selected.get("expiry"),
        selected.get("end_time"),
    )
    time_remaining = expires_at - now if expires_at else None
    if time_remaining is not None and time_remaining < 0:
        time_remaining = 0

    current = _coerce_float(selected.get("current"))
    target = _coerce_float(selected.get("target")) or _coerce_float(selected.get("required"))
    progress = _coerce_percent(
        selected.get("progress"),
        selected.get("percentage"),
        selected.get("completion"),
    )
    if progress is None and current is not None and target:
        progress = min(100.0, (current / target) * 100) if target else None

    targets = _extract_targets(selected)

    return {
        "title": _first_non_empty(selected.get("title"), selected.get("name")) or "Major Order",
        "description": _first_non_empty(selected.get("description"), selected.get("details")),
        "targets": targets,
        "progress": progress,
        "current": current,
        "target": target,
        "expires_at": expires_at,
        "time_remaining": time_remaining,
        "status": selected.get("status") or selected.get("state"),
    }


def _is_order_active(order: Mapping[str, Any], now: float) -> bool:
    state = str(order.get("status") or order.get("state") or "").lower()
    if state in {"active", "in_progress", "in-progress", "progress"}:
        return True
    expires = _parse_timestamp(
        order.get("expires_at"),
        order.get("expiresAt"),
        order.get("end_time"),
    )
    return expires is not None and expires > now


def _extract_major_orders(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        for key in ("major_orders", "majorOrders", "orders", "data"):
            entries = payload.get(key)
            if isinstance(entries, Sequence):
                return [entry for entry in entries if isinstance(entry, Mapping)]
    if isinstance(payload, Sequence):
        return [entry for entry in payload if isinstance(entry, Mapping)]
    return []


def _extract_targets(order: Mapping[str, Any]) -> list[str]:
    targets: list[str] = []
    for key in ("targets", "planets", "planet_targets", "planetTargets", "objective_planets"):
        value = order.get(key)
        if isinstance(value, Sequence):
            for entry in value:
                if isinstance(entry, Mapping):
                    name = _first_non_empty(entry.get("name"), entry.get("planet"), entry.get("title"))
                else:
                    name = _first_non_empty(entry)
                if name:
                    targets.append(str(name))
    return targets[:5]


def _normalise_news(payload: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    entries: Sequence[Any]
    if isinstance(payload, Mapping):
        entries = payload.get("news") or payload.get("data") or []
        if not isinstance(entries, Sequence):
            entries = []
    elif isinstance(payload, Sequence):
        entries = payload
    else:
        entries = []

    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        timestamp = _parse_timestamp(
            entry.get("published_at"),
            entry.get("timestamp"),
            entry.get("created_at"),
            entry.get("time"),
        )
        items.append(
            {
                "title": _first_non_empty(entry.get("title"), entry.get("headline")) or "Dispatch",
                "message": _first_non_empty(entry.get("message"), entry.get("body")),
                "timestamp": timestamp,
            }
        )

    items.sort(key=lambda item: item.get("timestamp") or 0, reverse=True)
    return items[:5]


def _build_war_snapshot(planets: list[dict[str, Any]]) -> dict[str, Any]:
    enemy_counter: Counter[str] = Counter()
    mission_counter: Counter[str] = Counter()
    for planet in planets:
        enemy = str(planet.get("enemy") or "Unknown enemy")
        enemy_counter[enemy] += 1
        mission = str(planet.get("mission_type") or "unknown")
        mission_counter[mission] += 1

    snapshot = {
        "active_fronts": len(planets),
        "fronts_by_enemy": [
            {"enemy": enemy, "count": count}
            for enemy, count in enemy_counter.most_common(5)
        ],
        "missions": [
            {"type": mission, "count": count}
            for mission, count in mission_counter.most_common(5)
        ],
    }
    return snapshot
