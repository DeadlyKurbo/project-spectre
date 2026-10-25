"""Guild-scoped country and city status persistence for TME drilldown."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from constants import ROOT_PREFIX
from storage_spaces import read_json, write_json
from tme_country_catalog import iso2_for

_ALLOWED_STATUS = {"enemy", "friendly", "contested"}
_MAX_CITY_OVERRIDES = 120


def _normalize_text(value: Any, fallback: str = "") -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = value.strip()
    return cleaned or fallback


def _normalize_status(value: Any, fallback: str = "contested") -> str:
    candidate = _normalize_text(value, fallback).lower()
    return candidate if candidate in _ALLOWED_STATUS else fallback


def _status_path(guild_id: str) -> str:
    cleaned = "".join(ch for ch in str(guild_id).strip() if ch.isdigit()) or "0"
    rel = f"operations/tme-country-status/{cleaned}.json"
    return f"{ROOT_PREFIX}/{rel}" if ROOT_PREFIX else rel


def default_country_status_record(iso2: str) -> dict[str, Any]:
    code = iso2_for(iso2) or str(iso2).strip().upper()
    return {
        "iso2": code,
        "autoStatus": "contested",
        "countryOverride": None,
        "cityOverrides": {},
    }


def sanitize_country_status_record(iso2: str, payload: Mapping[str, Any] | None) -> dict[str, Any]:
    record = default_country_status_record(iso2)
    if not isinstance(payload, Mapping):
        return record
    record["autoStatus"] = _normalize_status(payload.get("autoStatus"), "contested")
    country_override = payload.get("countryOverride")
    if country_override is None:
        record["countryOverride"] = None
    else:
        record["countryOverride"] = _normalize_status(country_override, "contested")
    raw_cities = payload.get("cityOverrides")
    cities: dict[str, str] = {}
    if isinstance(raw_cities, Mapping):
        for index, (city_name, status_value) in enumerate(raw_cities.items()):
            if index >= _MAX_CITY_OVERRIDES:
                break
            city = _normalize_text(city_name, "")
            if not city:
                continue
            cities[city] = _normalize_status(status_value, "contested")
    record["cityOverrides"] = cities
    return record


def _load_store(guild_id: str, *, with_etag: bool = False):
    path = _status_path(guild_id)
    data, etag = read_json(path, with_etag=True)
    if not isinstance(data, Mapping):
        data = {"countries": {}}
    countries = data.get("countries")
    if not isinstance(countries, Mapping):
        countries = {}
    normalized = {"countries": {str(k).upper(): v for k, v in countries.items()}}
    if with_etag:
        return normalized, etag
    return normalized


def load_country_status(guild_id: str, iso2: str, *, with_etag: bool = False):
    store, etag = _load_store(guild_id, with_etag=True)
    country_key = (iso2_for(iso2) or str(iso2).strip().upper())
    record = sanitize_country_status_record(country_key, store["countries"].get(country_key))
    if with_etag:
        return record, etag
    return record


def save_country_status(
    guild_id: str,
    iso2: str,
    payload: Mapping[str, Any] | None,
    *,
    etag: str | None = None,
) -> bool:
    store, _current_etag = _load_store(guild_id, with_etag=True)
    country_key = (iso2_for(iso2) or str(iso2).strip().upper())
    store["countries"][country_key] = sanitize_country_status_record(country_key, payload)
    path = _status_path(guild_id)
    return write_json(path, store, etag=etag)


def resolve_effective_country_status(record: Mapping[str, Any] | None) -> str:
    if not isinstance(record, Mapping):
        return "contested"
    override = record.get("countryOverride")
    if isinstance(override, str) and override.lower() in _ALLOWED_STATUS:
        return override.lower()
    auto = record.get("autoStatus")
    return _normalize_status(auto, "contested")


def city_status_for(record: Mapping[str, Any] | None, city_name: str, *, country_default: str = "contested") -> str:
    if not isinstance(record, Mapping):
        return _normalize_status(country_default, "contested")
    city_overrides = record.get("cityOverrides")
    if isinstance(city_overrides, Mapping):
        status = city_overrides.get(city_name)
        if isinstance(status, str) and status.lower() in _ALLOWED_STATUS:
            return status.lower()
    return _normalize_status(country_default, "contested")


def clone_record(record: Mapping[str, Any] | None) -> dict[str, Any]:
    return deepcopy(sanitize_country_status_record(str(record.get("iso2") if isinstance(record, Mapping) else "XX"), record))
