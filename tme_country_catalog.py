"""Curated country catalog for TME drilldown rollout scope."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class CountryEntry:
    iso2: str
    iso3: str
    name: str
    continent: str


_COUNTRIES: tuple[CountryEntry, ...] = (
    # Europe focus
    CountryEntry("FR", "FRA", "France", "Europe"),
    CountryEntry("IT", "ITA", "Italy", "Europe"),
    CountryEntry("DE", "DEU", "Germany", "Europe"),
    CountryEntry("BE", "BEL", "Belgium", "Europe"),
    CountryEntry("NL", "NLD", "Netherlands", "Europe"),
    CountryEntry("LU", "LUX", "Luxembourg", "Europe"),
    CountryEntry("RU", "RUS", "Russia", "Europe"),
    CountryEntry("GR", "GRC", "Greece", "Europe"),
    # Africa (largest by population)
    CountryEntry("NG", "NGA", "Nigeria", "Africa"),
    CountryEntry("ET", "ETH", "Ethiopia", "Africa"),
    CountryEntry("EG", "EGY", "Egypt", "Africa"),
    CountryEntry("CD", "COD", "Democratic Republic of the Congo", "Africa"),
    CountryEntry("TZ", "TZA", "Tanzania", "Africa"),
    CountryEntry("ZA", "ZAF", "South Africa", "Africa"),
    # Asia
    CountryEntry("CN", "CHN", "China", "Asia"),
    CountryEntry("IN", "IND", "India", "Asia"),
    CountryEntry("ID", "IDN", "Indonesia", "Asia"),
    CountryEntry("PK", "PAK", "Pakistan", "Asia"),
    CountryEntry("BD", "BGD", "Bangladesh", "Asia"),
    CountryEntry("JP", "JPN", "Japan", "Asia"),
    # North America
    CountryEntry("US", "USA", "United States", "North America"),
    CountryEntry("MX", "MEX", "Mexico", "North America"),
    CountryEntry("CA", "CAN", "Canada", "North America"),
    # South America
    CountryEntry("BR", "BRA", "Brazil", "South America"),
    CountryEntry("CO", "COL", "Colombia", "South America"),
    CountryEntry("AR", "ARG", "Argentina", "South America"),
    CountryEntry("PE", "PER", "Peru", "South America"),
    # Oceania
    CountryEntry("AU", "AUS", "Australia", "Oceania"),
    CountryEntry("PG", "PNG", "Papua New Guinea", "Oceania"),
    CountryEntry("NZ", "NZL", "New Zealand", "Oceania"),
)

_BY_ISO2 = {entry.iso2: entry for entry in _COUNTRIES}
_BY_ISO3 = {entry.iso3: entry for entry in _COUNTRIES}
_BY_NAME = {entry.name.lower(): entry for entry in _COUNTRIES}


def all_catalog_countries() -> tuple[CountryEntry, ...]:
    return _COUNTRIES


def allowed_iso2_codes() -> set[str]:
    return set(_BY_ISO2.keys())


def resolve_country(value: str | None) -> CountryEntry | None:
    if not value:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    upper = cleaned.upper()
    if upper in _BY_ISO2:
        return _BY_ISO2[upper]
    if upper in _BY_ISO3:
        return _BY_ISO3[upper]
    return _BY_NAME.get(cleaned.lower())


def iso2_for(value: str | None) -> str | None:
    entry = resolve_country(value)
    return entry.iso2 if entry else None


def names_for_iso2_codes(codes: Iterable[str]) -> list[str]:
    names: list[str] = []
    for code in codes:
        entry = _BY_ISO2.get(str(code).strip().upper())
        if entry:
            names.append(entry.name)
    return names
