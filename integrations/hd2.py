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
from typing import Sequence as TypingSequence

import httpx

__all__ = ["get_hd2_summary", "HelldiversIntegrationError"]


def _resolve_cache_ttl() -> float:
    raw = os.getenv("HD2_CACHE_TTL", "60")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 60.0
    return value if value >= 0 else 60.0


def _resolve_api_base() -> str:
    base = os.getenv("HD2_API_BASE")
    if base:
        base = base.strip()
    if not base:
        base = "https://api.live.prod.thehelldiversgame.com/api/WarSeason/current"
    return base.rstrip("/")


def _resolve_major_order_url() -> str | None:
    override = os.getenv("HD2_MAJOR_ORDER_URL")
    if override is not None:
        override = override.strip()
        return override or None
    return "https://helldiverstrainingmanual.com/api/v1/war/major-orders"


HD2_API_BASE = _resolve_api_base()
HD2_MAJOR_ORDER_URL = _resolve_major_order_url()
HD2_CACHE_TTL_SECONDS = _resolve_cache_ttl()
_LEGACY_API_BASE = "https://helldiverstrainingmanual.com/api/v1/war"
_LEGACY_PLANET_META_URL = "https://helldiverstrainingmanual.com/api/v1/planets"
_REQUEST_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_DEFAULT_HEADERS = {
    "User-Agent": "SpectreDashboard/HelldiversII (+https://github.com/OperatorSpectrum)",
    "Accept": "application/json",
}

_STATUS_ENDPOINTS = ("status", "WarStatus")
_INFO_ENDPOINTS = ("info", "WarInfo")
_NEWS_ENDPOINTS = ("news", "Newsfeed", "NewsFeed")
_CAMPAIGN_ENDPOINTS = ("campaign", "Campaign", "Campaigns")


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

    (
        status_data,
        info_data,
        major_orders,
        news_data,
        campaign_data,
        history_data,
        planet_meta_data,
    ) = await _fetch_hd2_payloads()
    summary = _build_summary(
        status_data,
        info_data,
        major_orders,
        news_data,
        campaign_data,
        history_data,
        planet_meta_data,
    )

    async with _hd2_lock:
        _hd2_cache["data"] = summary
        _hd2_cache["ts"] = time.time()
    return summary


async def _fetch_hd2_payloads() -> tuple[Any, Any, Any, Any, Any, Any, Any]:
    base_candidates = [HD2_API_BASE]
    if _LEGACY_API_BASE not in base_candidates:
        base_candidates.append(_LEGACY_API_BASE)

    last_error: HelldiversIntegrationError | None = None
    for base_url in base_candidates:
        try:
            return await _attempt_fetch_from_base(base_url)
        except HelldiversIntegrationError as exc:
            last_error = exc
            continue

    if last_error:
        raise last_error
    raise HelldiversIntegrationError("Failed to retrieve Helldivers data feed.")


async def _attempt_fetch_from_base(base_url: str) -> tuple[Any, Any, Any, Any, Any, Any, Any]:
    try:
        async with httpx.AsyncClient(
            base_url=base_url,
            headers=_DEFAULT_HEADERS,
            timeout=_REQUEST_TIMEOUT,
            follow_redirects=True,
        ) as client:
            major_order_resource = HD2_MAJOR_ORDER_URL or "major-orders"
            status_data = await _request_first_json(client, *_STATUS_ENDPOINTS)
            info_data = await _request_first_json(client, *_INFO_ENDPOINTS)
            major_orders = await _request_optional_json(client, major_order_resource, "MajorOrders", "major-orders")
            news_data = await _request_optional_json(client, *_NEWS_ENDPOINTS)
            campaign_data = await _request_optional_json(client, *_CAMPAIGN_ENDPOINTS)
            planet_meta_data = await _fetch_planet_meta_data(client)

            history_indices = _collect_planet_history_indices(status_data, info_data, planet_meta_data)
            history_data = await _fetch_planet_histories(client, history_indices)
    except HelldiversIntegrationError:
        raise
    except httpx.TimeoutException as exc:
        raise HelldiversIntegrationError("Timed out contacting the Helldivers data feed.") from exc
    except httpx.HTTPError as exc:
        raise HelldiversIntegrationError("Failed to contact the Helldivers data feed.") from exc
    return (
        status_data,
        info_data,
        major_orders,
        news_data,
        campaign_data,
        history_data,
        planet_meta_data,
    )


async def _fetch_planet_meta_data(client: httpx.AsyncClient) -> Any:
    try:
        return await _request_optional_json(
            client,
            "planets",
            "planets/info",
            "planet-info",
            "planets/meta",
            "Planets",
        )
    except HelldiversIntegrationError:
        pass

    async with httpx.AsyncClient(
        headers=_DEFAULT_HEADERS,
        timeout=_REQUEST_TIMEOUT,
        follow_redirects=True,
    ) as legacy_client:
        try:
            return await _request_json(legacy_client, _LEGACY_PLANET_META_URL)
        except HelldiversIntegrationError:
            return {}


async def _fetch_planet_histories(
    client: httpx.AsyncClient, planet_indices: Sequence[int]
) -> dict[int, Any]:
    if not planet_indices:
        return {}

    semaphore = asyncio.Semaphore(8)

    async def _fetch_single(planet_index: int) -> tuple[int, Any | None]:
        async with semaphore:
            try:
                payload = await _request_json(client, f"history/{planet_index}")
            except HelldiversIntegrationError:
                return planet_index, None
            return planet_index, payload

    history_entries = await asyncio.gather(
        *(_fetch_single(index) for index in planet_indices)
    )

    history: dict[int, Any] = {}
    for planet_index, payload in history_entries:
        if payload is not None:
            history[planet_index] = payload

    return history


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


async def _request_first_json(client: httpx.AsyncClient, *paths: str) -> Any:
    last_error: HelldiversIntegrationError | None = None
    for path in paths:
        if path is None:
            continue
        try:
            return await _request_json(client, path)
        except HelldiversIntegrationError as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise HelldiversIntegrationError("No valid paths provided for Helldivers API request.")


async def _request_optional_json(client: httpx.AsyncClient, *paths: str) -> Any:
    try:
        return await _request_first_json(client, *paths)
    except HelldiversIntegrationError:
        return {}


def _build_summary(
    status_data: Any,
    info_data: Any,
    major_orders_data: Any,
    news_data: Any,
    campaign_data: Any,
    history_data: Mapping[int, Any] | Any,
    planet_meta_data: Any,
) -> dict[str, Any]:
    now = time.time()
    info_lookup = _index_planet_info(info_data)

    planets: list[dict[str, Any]] = []
    for entry in _iter_planets(status_data):
        supplemental = None
        for key in _collect_planet_lookup_keys(entry):
            candidate = info_lookup.get(key)
            if candidate is not None:
                supplemental = candidate
                break
        planet = _normalise_planet(entry, now, supplemental)
        if planet:
            planets.append(planet)

    updated_at = _extract_payload_timestamp(status_data) or now

    def _planet_score(item: dict[str, Any]) -> tuple[float, float]:
        progress = _coerce_float(item.get("liberation"))
        priority = _coerce_float(item.get("priority")) or 0.0
        return (progress if progress is not None else -1.0, priority)

    hottest_planets = sorted(planets, key=_planet_score, reverse=True)[:5]

    summary: dict[str, Any] = {
        "hottest_planets": hottest_planets,
        "major_order": _normalise_major_order(major_orders_data, now),
        "news": _normalise_news(news_data),
        "war_snapshot": _build_war_snapshot(planets, status_data),
        "campaigns": campaign_data,
        "planet_history": history_data if isinstance(history_data, Mapping) else {},
        "planet_meta": planet_meta_data,
        "war_status": status_data,
        "war_info": info_data,
        "updated_at": updated_at,
        "feeds": {
            "status": status_data,
            "info": info_data,
            "news": news_data,
            "campaign": campaign_data,
            "history": history_data,
            "major_orders": major_orders_data,
            "planets": planet_meta_data,
        },
    }

    war_id = _extract_war_id(status_data, info_data)
    if war_id is not None:
        summary["war_id"] = war_id

    return summary


def _index_planet_info(payload: Any) -> dict[Any, Mapping[str, Any]]:
    index: dict[Any, Mapping[str, Any]] = {}

    def _merge_candidate(candidate: Mapping[str, Any]) -> None:
        combined: dict[str, Any] = {}
        planet_obj = candidate.get("planet") if isinstance(candidate.get("planet"), Mapping) else None
        if isinstance(planet_obj, Mapping):
            combined.update(planet_obj)
        combined.update(candidate)

        for key in _collect_planet_lookup_keys(combined):
            if key not in index:
                index[key] = combined

    if isinstance(payload, Mapping):
        values: list[Any] = []
        for key in (
            "planets",
            "planet_info",
            "planetInfo",
            "planetInfos",
            "data",
            "fronts",
        ):
            value = payload.get(key)
            if isinstance(value, Mapping):
                values.extend(value.values())
            elif isinstance(value, Sequence):
                values.extend(value)
        if not values:
            values = [payload]
    elif isinstance(payload, Sequence):
        values = list(payload)
    else:
        values = []

    for value in values:
        if isinstance(value, Mapping):
            _merge_candidate(value)

    return index


def _collect_planet_history_indices(*payloads: Any) -> list[int]:
    indices: set[int] = set()

    def _extend_from_entry(entry: Mapping[str, Any]) -> None:
        for candidate in _extract_planet_history_indices(entry):
            indices.add(candidate)

    for payload in payloads:
        entries: list[Mapping[str, Any]] = []
        if isinstance(payload, Mapping):
            entries.extend(_iter_planets(payload))
            planets_field = payload.get("planets")
            if isinstance(planets_field, Sequence):
                entries.extend(entry for entry in planets_field if isinstance(entry, Mapping))
        elif isinstance(payload, Sequence):
            entries.extend(entry for entry in payload if isinstance(entry, Mapping))

        for entry in entries:
            _extend_from_entry(entry)

    return sorted(indices)


def _extract_planet_history_indices(entry: Mapping[str, Any]) -> set[int]:
    indices: set[int] = set()

    def _maybe_add(candidate: Any) -> None:
        idx = _coerce_planet_index(candidate)
        if idx is not None:
            indices.add(idx)

    candidates: list[Any] = [
        entry.get("planet_index"),
        entry.get("planetIndex"),
        entry.get("index"),
        entry.get("id"),
    ]

    planet_obj = entry.get("planet") if isinstance(entry.get("planet"), Mapping) else None
    if isinstance(planet_obj, Mapping):
        candidates.extend(
            [
                planet_obj.get("planet_index"),
                planet_obj.get("planetIndex"),
                planet_obj.get("index"),
                planet_obj.get("id"),
            ]
        )

    for candidate in candidates:
        _maybe_add(candidate)

    return indices


def _coerce_planet_index(value: Any) -> int | None:
    normalised = _normalise_lookup_key(value)
    if isinstance(normalised, (int, float)) and math.isfinite(normalised):
        if isinstance(normalised, float):
            if not normalised.is_integer():
                return None
            normalised = int(normalised)
        if normalised >= 0:
            return int(normalised)
    return None


def _collect_planet_lookup_keys(entry: Mapping[str, Any]) -> list[Any]:
    keys: list[Any] = []
    candidates: list[Any] = [
        _extract_planet_identifier(entry),
        entry.get("planet_id"),
        entry.get("planetId"),
        entry.get("planet_index"),
        entry.get("planetIndex"),
        entry.get("index"),
        entry.get("id"),
        entry.get("name"),
    ]

    planet_obj = entry.get("planet") if isinstance(entry.get("planet"), Mapping) else None
    if isinstance(planet_obj, Mapping):
        candidates.extend(
            [
                planet_obj.get("id"),
                planet_obj.get("index"),
                planet_obj.get("planet_index"),
                planet_obj.get("planetIndex"),
                planet_obj.get("name"),
            ]
        )

    for candidate in candidates:
        key = _normalise_lookup_key(candidate)
        if key is not None and key not in keys:
            keys.append(key)

    return keys


def _normalise_lookup_key(value: Any) -> Any | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        if not math.isfinite(numeric):
            return None
        rounded = int(numeric)
        if float(rounded) == numeric:
            return rounded
        return numeric
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return text.lower()
        if not math.isfinite(number):
            return None
        rounded = int(number)
        if float(rounded) == number:
            return rounded
        return number
    return None


def _extract_payload_timestamp(payload: Any) -> float | None:
    if isinstance(payload, Mapping):
        return _parse_timestamp(
            payload.get("timestamp"),
            payload.get("updated_at"),
            payload.get("updatedAt"),
            payload.get("last_updated"),
            payload.get("lastUpdated"),
        )
    return None


def _extract_war_id(*payloads: Any) -> Any | None:
    for payload in payloads:
        if isinstance(payload, Mapping):
            for key in ("war_id", "warId", "current_war_id", "currentWarId", "id"):
                value = payload.get(key)
                if value is not None:
                    return value
    return None


def _iter_planets(payload: Any) -> list[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        return []

    seen_ids: set[Any] = set()
    planets: list[Mapping[str, Any]] = []

    for key in ("campaigns", "planets", "planet_status", "planetStatus", "planetInfos", "fronts"):
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
        numeric = float(value)
        if not math.isfinite(numeric):
            return None
        return numeric
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


def _first_numeric_from_sequence(value: Any) -> Any:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, Mapping)):
        for item in value:
            numeric = _coerce_float(item)
            if numeric is not None and numeric >= 0:
                return numeric
        for item in value:
            numeric = _coerce_float(item)
            if numeric is not None:
                return numeric
        return None
    return value


def _coerce_percent(*candidates: Any) -> float | None:
    for candidate in candidates:
        value = _coerce_float(_first_numeric_from_sequence(candidate))
        if value is None:
            continue
        if -1 <= value <= 1:
            value *= 100
        if value < -100.0:
            return -100.0
        return min(100.0, value)
    return None


def _first_float(*candidates: Any) -> float | None:
    for candidate in candidates:
        value = _coerce_float(candidate)
        if value is not None:
            return value
    return None


def _normalise_planet(
    entry: Mapping[str, Any],
    now: float,
    supplemental: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    planet_info: dict[str, Any] = {}
    if isinstance(supplemental, Mapping):
        planet_info.update(supplemental)
    embedded_planet = entry.get("planet") if isinstance(entry.get("planet"), Mapping) else None
    if isinstance(embedded_planet, Mapping):
        planet_info.update(embedded_planet)

    name = _first_non_empty(
        planet_info.get("name"),
        planet_info.get("planet_name"),
        planet_info.get("planetName"),
        entry.get("planet_name"),
        entry.get("planetName"),
        entry.get("name"),
    ) or "Unknown planet"

    enemy_info = entry.get("enemy") if isinstance(entry.get("enemy"), Mapping) else {}
    supplemental_enemy_candidate = supplemental.get("enemy") if isinstance(supplemental, Mapping) else None
    supplemental_enemy = supplemental_enemy_candidate if isinstance(supplemental_enemy_candidate, Mapping) else {}

    enemy = _first_non_empty(
        enemy_info.get("name"),
        enemy_info.get("type"),
        entry.get("enemy"),
        entry.get("enemy_type"),
        planet_info.get("enemy"),
        supplemental_enemy.get("name") if supplemental_enemy else None,
        supplemental_enemy.get("type") if supplemental_enemy else None,
    )

    mission_label = _first_non_empty(
        entry.get("mission_type"),
        entry.get("type"),
        entry.get("mission"),
        entry.get("operation_type"),
        planet_info.get("mission_type"),
        planet_info.get("type"),
        supplemental.get("mission_type") if isinstance(supplemental, Mapping) else None,
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
        planet_info.get("liberation_percent"),
        planet_info.get("liberationPercent"),
    )

    current = _coerce_float(entry.get("current"))
    if current is None:
        current = _coerce_float(planet_info.get("current"))
    target = _coerce_float(entry.get("target")) or _coerce_float(entry.get("required"))
    if target is None:
        target = _coerce_float(planet_info.get("target")) or _coerce_float(planet_info.get("required"))
    if progress is None and current is not None and target:
        progress = min(100.0, (current / target) * 100) if target else None

    status = _first_non_empty(
        entry.get("status"),
        entry.get("state"),
        planet_info.get("state"),
        planet_info.get("status"),
        supplemental.get("status") if isinstance(supplemental, Mapping) else None,
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
            planet_info.get("endTime"),
            planet_info.get("expiry"),
        )
    time_remaining = expires_at - now if expires_at else None
    if time_remaining is not None and time_remaining < 0:
        time_remaining = 0

    priority = (
        _coerce_float(entry.get("priority"))
        or _coerce_float(planet_info.get("priority"))
        or _coerce_float(planet_info.get("priority_score"))
        or 0.0
    )

    identifier = _extract_planet_identifier(entry)
    if identifier is None and isinstance(supplemental, Mapping):
        identifier = (
            supplemental.get("id")
            or supplemental.get("index")
            or supplemental.get("planet_index")
            or supplemental.get("planetIndex")
            or supplemental.get("name")
        )

    return {
        "id": identifier,
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


def _get_nested_value(source: Mapping[str, Any], path: TypingSequence[str]) -> Any:
    current: Any = source
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current


def _extract_text_field(source: Mapping[str, Any], *paths: Any) -> str | None:
    for path in paths:
        if isinstance(path, str):
            value = source.get(path)
        else:
            value = _get_nested_value(source, tuple(path))
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned
    return None


def _normalise_major_order(payload: Any, now: float) -> dict[str, Any] | None:
    candidates = _extract_major_orders(payload)
    if not candidates:
        return None

    def _order_sort_key(order: Mapping[str, Any]) -> tuple[float, float, float]:
        expires = _parse_timestamp(
            order.get("expires_at"),
            order.get("expiresAt"),
            order.get("expiry"),
            order.get("end_time"),
        )
        recency = _extract_order_recency(order)
        return (
            0 if _is_order_active(order, now) else 1,
            -(expires or 0),
            -(recency or 0),
        )

    selected = sorted(candidates, key=_order_sort_key)[0]

    expires_at = _parse_timestamp(
        selected.get("expires_at"),
        selected.get("expiresAt"),
        selected.get("expiry"),
        selected.get("end_time"),
        selected.get("endTime"),
    )
    expires_in = _first_float(selected.get("expires_in"), selected.get("expiresIn"))
    if expires_at is None and expires_in is not None:
        expires_at = now + expires_in
    time_remaining = expires_at - now if expires_at else None
    if time_remaining is not None and time_remaining < 0:
        time_remaining = 0

    current = _coerce_float(selected.get("current"))
    target = _coerce_float(selected.get("target")) or _coerce_float(selected.get("required"))
    progress = _coerce_percent(
        selected.get("progress"),
        selected.get("percentage"),
        selected.get("completion"),
        selected.get("progress_percent"),
        selected.get("progressPercent"),
    )
    if progress is None and current is not None and target:
        progress = min(100.0, (current / target) * 100) if target else None

    if progress is None or current is None or target is None:
        derived = _aggregate_objective_progress(selected)
        if progress is None and derived["progress"] is not None:
            progress = derived["progress"]
        if current is None and derived["current"] is not None:
            current = derived["current"]
        if target is None and derived["target"] is not None:
            target = derived["target"]

    targets = _extract_targets(selected)

    title = _extract_text_field(
        selected,
        "title",
        "name",
        "headline",
        "briefing_title",
        "briefingTitle",
        ("setting", "overrideTitle"),
        ("setting", "title"),
        ("briefing", "title"),
        ("briefing", "headline"),
        ("briefing", "name"),
    )

    description = _extract_text_field(
        selected,
        "description",
        "details",
        "summary",
        "message",
        "body",
        "briefing",
        "briefing_text",
        "briefingText",
        ("setting", "overrideBrief"),
        ("setting", "briefing"),
        ("setting", "description"),
        ("briefing", "description"),
        ("briefing", "summary"),
        ("briefing", "text"),
        ("briefing", "message"),
        ("briefing", "body"),
    )

    return {
        "title": title or "Major Order",
        "description": description,
        "targets": targets,
        "progress": progress,
        "current": current,
        "target": target,
        "expires_at": expires_at,
        "time_remaining": time_remaining,
        "status": selected.get("status") or selected.get("state"),
        "objectives": _normalise_major_order_objectives(selected),
        "reward": _extract_reward(selected),
    }


def _is_order_active(order: Mapping[str, Any], now: float) -> bool:
    state = str(order.get("status") or order.get("state") or "").lower()
    if state in {
        "active",
        "in_progress",
        "in-progress",
        "progress",
        "ongoing",
        "live",
        "current",
    }:
        return True

    expires = _parse_timestamp(
        order.get("expires_at"),
        order.get("expiresAt"),
        order.get("end_time"),
    )
    if expires is not None and expires > now:
        return True

    starts = _parse_timestamp(
        order.get("starts_at"),
        order.get("start_at"),
        order.get("start_time"),
        order.get("startTime"),
        order.get("activated_at"),
        order.get("activatedAt"),
        order.get("issued_at"),
        order.get("issuedAt"),
        order.get("published_at"),
        order.get("publishedAt"),
    )
    if starts is not None and starts > now:
        return False
    if starts is not None and starts <= now:
        # Treat orders that have already started as active even if no expiry/status is available.
        return True
    return False


def _extract_order_recency(order: Mapping[str, Any]) -> float | None:
    timestamps: list[float] = []

    for field in (
        "starts_at",
        "start_at",
        "start_time",
        "startTime",
        "start_time_seconds",
        "startTimeSeconds",
        "start_time_secs",
        "startTimeSecs",
        "activated_at",
        "activatedAt",
        "issued_at",
        "issuedAt",
        "published_at",
        "publishedAt",
        "updated_at",
        "updatedAt",
        "last_updated",
        "lastUpdated",
    ):
        value = _parse_timestamp(order.get(field))
        if value is not None:
            timestamps.append(value)

    identifier = _coerce_float(order.get("id"))
    if identifier is not None:
        timestamps.append(identifier)

    if not timestamps:
        return None
    return max(timestamps)


def _extract_major_orders(payload: Any) -> list[Mapping[str, Any]]:
    orders: list[Mapping[str, Any]] = []
    visited: set[int] = set()

    def _walk(value: Any) -> None:
        if isinstance(value, Mapping):
            obj_id = id(value)
            if obj_id in visited:
                return
            visited.add(obj_id)
            if _looks_like_major_order(value):
                orders.append(value)
            for child in value.values():
                if isinstance(child, (Mapping, Sequence)) and not isinstance(child, (str, bytes, bytearray)):
                    _walk(child)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            obj_id = id(value)
            if obj_id in visited:
                return
            visited.add(obj_id)
            for item in value:
                _walk(item)

    _walk(payload)
    return orders


def _aggregate_objective_progress(order: Mapping[str, Any]) -> dict[str, float | None]:
    sequences = []
    for key in _OBJECTIVE_SOURCE_KEYS:
        value = order.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            sequences.append(value)

    current_total = 0.0
    target_total = 0.0
    have_current = False
    have_target = False

    for sequence in sequences:
        for entry in sequence:
            if not isinstance(entry, Mapping):
                continue
            entry_current = _first_float(
                entry.get("current"),
                entry.get("current_value"),
                entry.get("currentValue"),
                entry.get("progress_value"),
                entry.get("progressValue"),
                entry.get("completed"),
                entry.get("achieved"),
            )
            entry_target = _first_float(
                entry.get("target"),
                entry.get("target_value"),
                entry.get("targetValue"),
                entry.get("required"),
                entry.get("requirement"),
                entry.get("goal"),
                entry.get("value"),
                entry.get("amount"),
            )
            entry_progress = _coerce_percent(
                entry.get("progress"),
                entry.get("percentage"),
                entry.get("completion"),
                entry.get("progress_percent"),
                entry.get("progressPercent"),
            )

            if entry_current is None and entry_target is not None and entry_progress is not None:
                entry_current = (entry_progress / 100.0) * entry_target
            elif (
                entry_target is None
                and entry_current is not None
                and entry_progress is not None
                and entry_progress > 0
            ):
                entry_target = entry_current / (entry_progress / 100.0)

            if entry_current is not None:
                current_total += entry_current
                have_current = True
            if entry_target is not None:
                target_total += entry_target
                have_target = True

    progress = None
    if have_current and have_target and target_total > 0:
        progress = min(100.0, (current_total / target_total) * 100.0)

    return {
        "current": current_total if have_current else None,
        "target": target_total if have_target else None,
        "progress": progress,
    }


def _extract_targets(order: Mapping[str, Any]) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()
    for key in _OBJECTIVE_SOURCE_KEYS:
        value = order.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for entry in value:
                if isinstance(entry, Mapping):
                    name = _first_non_empty(
                        entry.get("name"),
                        entry.get("planet"),
                        entry.get("planet_name"),
                        entry.get("planetName"),
                        entry.get("title"),
                        entry.get("objective"),
                        entry.get("label"),
                        entry.get("description"),
                        _get_nested_value(entry, ("planet", "name")),
                    )
                else:
                    name = _first_non_empty(entry)
                if name:
                    text = str(name)
                    if text not in seen:
                        seen.add(text)
                        targets.append(text)
    return targets[:5]


def _normalise_major_order_objectives(order: Mapping[str, Any]) -> list[dict[str, Any]]:
    progress_series: list[float | None] | None = None
    raw_progress = order.get("progress")
    if isinstance(raw_progress, Sequence) and not isinstance(raw_progress, (str, bytes, bytearray)):
        progress_series = []
        for value in raw_progress:
            percent = _coerce_percent(value)
            if percent is not None:
                progress_series.append(percent)
                continue
            numeric = _first_float(value)
            progress_series.append(numeric if numeric is not None else None)

    objectives: list[dict[str, Any]] = []
    progress_index = 0

    for key in _OBJECTIVE_SOURCE_KEYS:
        value = order.get(key)
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            continue
        for entry in value:
            if isinstance(entry, Mapping):
                label = _first_non_empty(
                    entry.get("name"),
                    entry.get("planet"),
                    entry.get("planet_name"),
                    entry.get("planetName"),
                    entry.get("title"),
                    entry.get("objective"),
                    entry.get("label"),
                    entry.get("description"),
                    _get_nested_value(entry, ("planet", "name")),
                )
                current = _first_float(
                    entry.get("current"),
                    entry.get("current_value"),
                    entry.get("currentValue"),
                    entry.get("progress_value"),
                    entry.get("progressValue"),
                    entry.get("completed"),
                    entry.get("achieved"),
                )
                target = _first_float(
                    entry.get("target"),
                    entry.get("target_value"),
                    entry.get("targetValue"),
                    entry.get("required"),
                    entry.get("requirement"),
                    entry.get("goal"),
                    entry.get("value"),
                    entry.get("amount"),
                )
                progress = _coerce_percent(
                    entry.get("progress"),
                    entry.get("percentage"),
                    entry.get("completion"),
                    entry.get("progress_percent"),
                    entry.get("progressPercent"),
                )
            else:
                label = _first_non_empty(entry)
                current = None
                target = None
                progress = None

            if progress is None and current is not None and target:
                progress = min(100.0, (current / target) * 100.0) if target else None
            if (
                progress is None
                and progress_series is not None
                and 0 <= progress_index < len(progress_series)
            ):
                progress = progress_series[progress_index]

            objectives.append(
                {
                    "label": str(label) if label else f"Objective {len(objectives) + 1}",
                    "current": current,
                    "target": target,
                    "progress": progress,
                    "status": entry.get("status") if isinstance(entry, Mapping) else None,
                }
            )
            progress_index += 1

    if not objectives and progress_series is not None:
        for idx, value in enumerate(progress_series, start=1):
            objectives.append(
                {
                    "label": f"Objective {idx}",
                    "current": None,
                    "target": None,
                    "progress": value,
                    "status": None,
                }
            )

    return objectives


def _extract_reward(order: Mapping[str, Any]) -> dict[str, Any] | None:
    rewards: list[Mapping[str, Any]] = []
    setting = order.get("setting") if isinstance(order.get("setting"), Mapping) else None

    def _append_reward(value: Any) -> None:
        if isinstance(value, Mapping):
            rewards.append(value)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for entry in value:
                if isinstance(entry, Mapping):
                    rewards.append(entry)

    _append_reward(order.get("reward"))
    _append_reward(order.get("rewards"))
    if setting:
        _append_reward(setting.get("reward"))
        _append_reward(setting.get("rewards"))

    for reward in rewards:
        amount = _first_float(reward.get("amount"), reward.get("value"), reward.get("quantity"))
        label = _first_non_empty(reward.get("title"), reward.get("name"), reward.get("description"), reward.get("type"))
        if amount is None and not label:
            continue
        return {
            "amount": amount,
            "label": str(label) if label else "Reward",
        }

    return None


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


def _build_war_snapshot(planets: list[dict[str, Any]], status_payload: Any) -> dict[str, Any]:
    enemy_counter: Counter[str] = Counter()
    mission_counter: Counter[str] = Counter()
    for planet in planets:
        enemy = str(planet.get("enemy") or "Unknown enemy")
        enemy_counter[enemy] += 1
        mission = str(planet.get("mission_type") or "unknown")
        mission_counter[mission] += 1

    stats = _extract_global_stats(status_payload, planets)

    snapshot = {
        "active_fronts": len(planets),
        "planets_liberated": stats.get("planets_liberated"),
        "current_liberation_percent": stats.get("current_liberation_percent"),
        "total_casualties": stats.get("total_casualties"),
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


def _extract_global_stats(status_payload: Any, planets: list[dict[str, Any]]) -> dict[str, Any]:
    stats = {
        "planets_liberated": _search_global_metric(
            status_payload,
            (
                "planets_liberated",
                "planetsLiberated",
                "liberated_planets",
                "liberatedPlanets",
            ),
        ),
        "current_liberation_percent": _search_global_metric(
            status_payload,
            (
                "current_liberation",
                "currentLiberation",
                "current_liberation_percent",
                "currentLiberationPercent",
                "liberation_percent",
                "liberationPercent",
                "liberation",
                "galaxy_liberation",
                "galaxyLiberation",
            ),
            percent=True,
        ),
        "total_casualties": _search_global_metric(
            status_payload,
            (
                "total_casualties",
                "totalCasualties",
                "casualties",
                "casualty_count",
                "casualtyCount",
                "casualties_total",
                "casualtiesTotal",
            ),
        ),
    }

    if stats["planets_liberated"] is None and planets:
        stats["planets_liberated"] = _count_liberated_planets(planets)

    return stats


def _count_liberated_planets(planets: list[dict[str, Any]]) -> int:
    liberated = 0
    for planet in planets:
        progress = _coerce_float(planet.get("liberation"))
        if progress is None:
            continue
        if progress >= 100:
            liberated += 1
    return liberated


_PLANET_CONTAINER_KEYS = {"campaigns", "planets", "planet_status", "planetStatus", "planetInfos", "fronts"}
_OBJECTIVE_SOURCE_KEYS = (
    "targets",
    "planets",
    "planet_targets",
    "planetTargets",
    "objective_planets",
    "objectives",
    "tasks",
    "requirements",
    "goals",
    "assignments",
)


def _search_global_metric(
    payload: Any,
    keys: Sequence[str],
    *,
    percent: bool = False,
) -> float | None:
    if payload is None:
        return None

    visited: set[int] = set()

    def _walk(value: Any) -> float | None:
        if isinstance(value, Mapping):
            obj_id = id(value)
            if obj_id in visited:
                return None
            visited.add(obj_id)
            for key in keys:
                if key in value:
                    candidate = value.get(key)
                    converted = _coerce_percent(candidate) if percent else _coerce_float(candidate)
                    if converted is not None:
                        return converted
            for child_key, child_value in value.items():
                if child_key in _PLANET_CONTAINER_KEYS:
                    continue
                if isinstance(child_value, (Mapping, Sequence)) and not isinstance(child_value, (str, bytes, bytearray)):
                    result = _walk(child_value)
                    if result is not None:
                        return result
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            obj_id = id(value)
            if obj_id in visited:
                return None
            visited.add(obj_id)
            for item in value:
                result = _walk(item)
                if result is not None:
                    return result
        return None

    return _walk(payload)


def _looks_like_major_order(candidate: Mapping[str, Any]) -> bool:
    title = _extract_text_field(
        candidate,
        "title",
        "name",
        "headline",
        "briefing_title",
        "briefingTitle",
        ("setting", "overrideTitle"),
        ("setting", "title"),
        ("briefing", "title"),
        ("briefing", "headline"),
        ("briefing", "name"),
    )
    description = _extract_text_field(
        candidate,
        "description",
        "details",
        "summary",
        "briefing",
        "message",
        "body",
        "briefing_text",
        "briefingText",
        ("setting", "overrideBrief"),
        ("setting", "briefing"),
        ("setting", "description"),
        ("briefing", "summary"),
        ("briefing", "text"),
        ("briefing", "message"),
        ("briefing", "body"),
    )

    narrative_keys = {
        "targets",
        "planets",
        "planet_targets",
        "planetTargets",
        "objective_planets",
        "objectives",
        "tasks",
        "requirements",
        "goals",
        "status",
        "state",
        "progress",
        "percentage",
        "current",
        "target",
        "required",
        "expires_at",
        "expiresAt",
        "expiry",
        "end_time",
        "endTime",
    }

    if title or description:
        return any(candidate.get(key) not in (None, "", [], {}) for key in narrative_keys)

    return False
