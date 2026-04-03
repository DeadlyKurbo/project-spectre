"""External geo provider adapter for TME country drilldown."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

import httpx

from tme_country_catalog import CountryEntry, resolve_country

_CITY_DATASET = (
    "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/"
    "geonames-all-cities-with-a-population-1000/records"
)
_CACHE_TTL_SECONDS = 60 * 30
_REQUEST_TIMEOUT_SECONDS = 10
_MAX_CITY_COUNT = 25

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

_FALLBACK_CAPITALS: dict[str, tuple[str, float, float, int]] = {
    "FR": ("Paris", 48.8566, 2.3522, 2100000),
    "IT": ("Rome", 41.9028, 12.4964, 2800000),
    "DE": ("Berlin", 52.52, 13.405, 3600000),
    "BE": ("Brussels", 50.8503, 4.3517, 185000),
    "NL": ("Amsterdam", 52.3676, 4.9041, 872000),
    "LU": ("Luxembourg", 49.6117, 6.1319, 130000),
    "RU": ("Moscow", 55.7558, 37.6173, 13000000),
    "GR": ("Athens", 37.9838, 23.7275, 3150000),
    "US": ("Washington", 38.9072, -77.0369, 680000),
    "CN": ("Beijing", 39.9042, 116.4074, 21500000),
    "IN": ("New Delhi", 28.6139, 77.209, 17000000),
}


def _now() -> float:
    return time.time()


def _extract_coordinates(raw: dict[str, Any]) -> tuple[float | None, float | None]:
    coords = raw.get("coordinates")
    if isinstance(coords, dict):
        lat = coords.get("lat")
        lon = coords.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return float(lat), float(lon)
    if isinstance(raw.get("latitude"), (int, float)) and isinstance(raw.get("longitude"), (int, float)):
        return float(raw["latitude"]), float(raw["longitude"])
    if isinstance(raw.get("lat"), (int, float)) and isinstance(raw.get("lon"), (int, float)):
        return float(raw["lat"]), float(raw["lon"])
    if isinstance(raw.get("geo_point_2d"), dict):
        point = raw["geo_point_2d"]
        if isinstance(point.get("lat"), (int, float)) and isinstance(point.get("lon"), (int, float)):
            return float(point["lat"]), float(point["lon"])
    return None, None


def _request_json(url: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with httpx.Client(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
                response = client.get(url)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            return {}
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < 2:
                time.sleep(0.25 * (attempt + 1))
                continue
    if last_error:
        raise last_error
    return {}


def _build_city_query(country: CountryEntry, limit: int) -> str:
    where_expr = quote(f'country_code="{country.iso2}"')
    select_expr = quote("name,cou_name_en,country_code,population,coordinates")
    return (
        f"{_CITY_DATASET}?select={select_expr}&where={where_expr}"
        f"&order_by=population%20desc&limit={max(1, min(limit, _MAX_CITY_COUNT))}"
    )


def _fallback_payload(country: CountryEntry) -> dict[str, Any]:
    city = _FALLBACK_CAPITALS.get(country.iso2)
    cities: list[dict[str, Any]] = []
    if city:
        city_name, lat, lon, population = city
        cities.append(
            {
                "name": city_name,
                "lat": float(lat),
                "lon": float(lon),
                "population": int(population),
                "iso2": country.iso2,
                "source": "fallback",
            }
        )
    return {
        "country": {
            "iso2": country.iso2,
            "iso3": country.iso3,
            "name": country.name,
            "continent": country.continent,
        },
        "cities": cities,
        "source": "fallback",
    }


def get_country_drilldown_data(country_value: str, *, max_cities: int = 15) -> dict[str, Any]:
    country = resolve_country(country_value)
    if not country:
        raise ValueError("Unsupported country")
    cache_key = f"{country.iso2}:{max_cities}"
    cached = _CACHE.get(cache_key)
    if cached and (_now() - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    try:
        url = _build_city_query(country, max_cities)
        payload = _request_json(url)
        records = payload.get("results") if isinstance(payload, dict) else []
        normalized: list[dict[str, Any]] = []
        if isinstance(records, list):
            for entry in records:
                if not isinstance(entry, dict):
                    continue
                lat, lon = _extract_coordinates(entry)
                if lat is None or lon is None:
                    continue
                name = str(entry.get("name") or "").strip()
                if not name:
                    continue
                population = entry.get("population")
                normalized.append(
                    {
                        "name": name,
                        "lat": float(lat),
                        "lon": float(lon),
                        "population": int(population) if isinstance(population, (int, float)) else 0,
                        "iso2": country.iso2,
                        "source": "external",
                    }
                )
        if not normalized:
            raise ValueError("No city records from provider")
        result = {
            "country": {
                "iso2": country.iso2,
                "iso3": country.iso3,
                "name": country.name,
                "continent": country.continent,
            },
            "cities": normalized[: max(1, min(max_cities, _MAX_CITY_COUNT))],
            "source": "external",
        }
    except Exception:  # noqa: BLE001
        result = _fallback_payload(country)

    _CACHE[cache_key] = (_now(), result)
    return result
