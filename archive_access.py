"""Resolve a website visitor's archive standing from live Discord data.

The Discord archive lets a member open a file when they own the guild, have
the Administrator permission, hold one of the file's required roles, or have
temporary clearance; during a lockdown only High Command gets in at all. The
website signs people in with Discord, so it asks the bot for the same member
record and applies the same rules, rather than trusting what the browser
session last saw.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping

import httpx

import constants
import server_config

ADMINISTRATOR = 0x8
# Role changes in Discord reach the website within this window (or at once
# with the archive page's Resync button).
MEMBER_TTL_SECONDS = 30.0
GUILD_TTL_SECONDS = 120.0


class DiscordLookupError(Exception):
    """Discord could not be asked, so access cannot be verified."""


@dataclass
class Standing:
    user_id: str
    roles: set[int] = field(default_factory=set)
    is_owner: bool = False
    is_admin: bool = False
    is_high_command: bool = False
    # False when the bot token is missing and only the OAuth guild list was
    # available: roles are then unknown and only open files are readable.
    roles_verified: bool = True


_member_cache: dict[tuple[str, str], tuple[float, dict[str, Any] | None]] = {}
_guild_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
_CACHE_PRUNE_SIZE = 2048


def _remember(cache: dict, key: Any, value: Any, ttl: float) -> None:
    now = time.monotonic()
    if len(cache) >= _CACHE_PRUNE_SIZE:
        for stale in [k for k, (stamp, _v) in cache.items() if now - stamp >= ttl]:
            cache.pop(stale, None)
    cache[key] = (now, value)


async def _bot_get(api: str, token: str, path: str) -> dict[str, Any] | None:
    """GET ``path`` as the bot; ``None`` when the bot or member is not in the guild."""

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{api}{path}", headers={"Authorization": f"Bot {token}"})
    except httpx.HTTPError as exc:
        raise DiscordLookupError(str(exc)) from exc
    if response.status_code in (403, 404):
        return None
    if response.status_code >= 400:
        raise DiscordLookupError(f"Discord answered {response.status_code} for {path}")
    data = response.json()
    return data if isinstance(data, dict) else None


async def fetch_member(api: str, token: str, guild_id: str, user_id: str, *, force: bool = False) -> dict[str, Any] | None:
    key = (str(guild_id), str(user_id))
    cached = _member_cache.get(key)
    if cached and not force and time.monotonic() - cached[0] < MEMBER_TTL_SECONDS:
        return cached[1]
    member = await _bot_get(api, token, f"/guilds/{guild_id}/members/{user_id}")
    _remember(_member_cache, key, member, MEMBER_TTL_SECONDS)
    return member


async def fetch_guild(api: str, token: str, guild_id: str, *, force: bool = False) -> dict[str, Any] | None:
    key = str(guild_id)
    cached = _guild_cache.get(key)
    if cached and not force and time.monotonic() - cached[0] < GUILD_TTL_SECONDS:
        return cached[1]
    guild = await _bot_get(api, token, f"/guilds/{guild_id}")
    _remember(_guild_cache, key, guild, GUILD_TTL_SECONDS)
    return guild


def _role_ids(values: Any) -> set[int]:
    roles: set[int] = set()
    for value in values if isinstance(values, (list, tuple, set)) else []:
        try:
            roles.add(int(value))
        except (TypeError, ValueError):
            continue
    return roles


def member_permissions(guild: Mapping[str, Any], roles: set[int]) -> int:
    """Combine @everyone's and the member's role permissions, as Discord does."""

    by_id: dict[int, Mapping[str, Any]] = {}
    for role in guild.get("roles") or []:
        if isinstance(role, Mapping):
            try:
                by_id[int(role.get("id"))] = role
            except (TypeError, ValueError):
                continue
    permissions = 0
    try:
        everyone_id = int(guild.get("id"))
    except (TypeError, ValueError):
        everyone_id = None
    for role_id in ({everyone_id} if everyone_id is not None else set()) | roles:
        role = by_id.get(role_id)
        if role is None:
            continue
        try:
            permissions |= int(role.get("permissions") or 0)
        except (TypeError, ValueError):
            continue
    return permissions


def high_command_role_id(guild_id: int) -> int:
    """Mirror archivist._archivist_role_ids for the High Command role."""

    cfg = server_config.get_server_config(guild_id)
    if isinstance(cfg, dict):
        try:
            configured = int(str(cfg.get("HIGH_COMMAND_ROLE_ID") or "").strip() or 0)
        except ValueError:
            configured = 0
        if configured:
            return configured
    return int(constants.HIGH_COMMAND_ROLE_ID or 0)


def standing_from_discord(
    guild_id: int, user_id: str, member: Mapping[str, Any], guild: Mapping[str, Any]
) -> Standing:
    roles = _role_ids(member.get("roles"))
    is_owner = str(guild.get("owner_id") or "") == str(user_id)
    is_admin = is_owner or bool(member_permissions(guild, roles) & ADMINISTRATOR)
    high_command = high_command_role_id(guild_id)
    return Standing(
        user_id=str(user_id),
        roles=roles,
        is_owner=is_owner,
        is_admin=is_admin,
        is_high_command=is_admin or (bool(high_command) and high_command in roles),
    )
