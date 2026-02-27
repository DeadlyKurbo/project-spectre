"""Environment-driven configuration for the Spectre bot."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


_DEF_INVITE = (
    "https://discord.com/oauth2/authorize?client_id=1121761480145117224"
    "&permissions=8&response_type=code"
    "&redirect_uri=https%3A%2F%2Fproject-spectre.com%2Fauth%2Fcallback"
    "&integration_type=0"
    "&scope=guilds.members.read+dm_channels.messages.write+applications.commands+guilds.channels.read+bot+guilds.join"
)
_DEF_DASHBOARD = "https://project-spectre.com/"


def _clean(value: Optional[str]) -> Optional[str]:
    """Normalize environment strings by stripping whitespace."""

    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class SpectreSettings:
    """Runtime configuration derived from process environment variables."""

    token: Optional[str]
    token_source: Optional[str]
    bot_invite_url: Optional[str]
    dashboard_url: Optional[str]
    hiccup_chance: float
    backup_interval_hours: float
    lazarus_status_interval: int

    @classmethod
    def from_env(cls) -> "SpectreSettings":
        """Build a settings instance by reading supported environment variables."""

        primary_token = _clean(os.getenv("DISCORD_TOKEN"))
        fallback_token = _clean(os.getenv("DISCORD_BOT_TOKEN"))
        token_source: Optional[str]
        if primary_token:
            token = primary_token
            token_source = "DISCORD_TOKEN"
        elif fallback_token:
            token = fallback_token
            token_source = "DISCORD_BOT_TOKEN"
        else:
            token = None
            token_source = None

        invite = _clean(os.getenv("BOT_INVITE_URL")) or _DEF_INVITE
        dashboard = _clean(os.getenv("SPECTRE_DASHBOARD_URL")) or _DEF_DASHBOARD

        return cls(
            token=token,
            token_source=token_source,
            bot_invite_url=invite,
            dashboard_url=dashboard,
            hiccup_chance=_float_env("HICCUP_CHANCE", 0.0),
            backup_interval_hours=_float_env("BACKUP_INTERVAL_HOURS", 0.5),
            lazarus_status_interval=_int_env("LAZARUS_STATUS_INTERVAL", 5),
        )


__all__ = ["SpectreSettings"]
