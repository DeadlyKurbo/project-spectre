"""Shared runtime context for the Spectre application."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional

import logging

from nextcord.ext import commands, tasks
from lazarus import LazarusAI
from server_config import get_dashboard_logging_channels, get_server_config

from .settings import SpectreSettings


@dataclass
class SpectreContext:
    """Container holding shared objects that multiple modules rely on."""

    bot: commands.Bot
    settings: SpectreSettings
    logger: logging.Logger
    lazarus_ai: LazarusAI
    guild_ids: list[int]
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    backup_loop: Optional[tasks.Loop] = None
    commands_synced: bool = False

    async def _resolve_admin_log_channel_ids(self) -> list[int]:
        """Return unique admin log channel IDs across configured guilds."""

        guild_ids = set(self.guild_ids)
        if not guild_ids:
            guild_ids = {int(guild.id) for guild in self.bot.guilds}

        channel_ids: set[int] = set()
        for guild_id in guild_ids:
            cfg = get_server_config(int(guild_id))
            if isinstance(cfg, dict):
                for key in ("ADMIN_LOG_CHANNEL_ID", "SECURITY_LOG_CHANNEL_ID"):
                    raw_channel_id = cfg.get(key)
                    if isinstance(raw_channel_id, int) and raw_channel_id > 0:
                        channel_ids.add(raw_channel_id)
                dashboard_channels = get_dashboard_logging_channels(int(guild_id))
                admin_log_channel = dashboard_channels.get("admin_log")
                if isinstance(admin_log_channel, int) and admin_log_channel > 0:
                    channel_ids.add(admin_log_channel)

        return sorted(channel_ids)

    async def log_action(self, message: str, *, broadcast: bool = True) -> None:
        """Log actions and mirror them to configured admin channels."""

        if broadcast:
            self.logger.info("Action log entry: %s", message)
        else:
            self.logger.debug("Action log entry: %s", message)
            return

        channel_ids = await self._resolve_admin_log_channel_ids()
        if not channel_ids:
            return

        for channel_id in channel_ids:
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except Exception:
                    self.logger.warning(
                        "Unable to resolve admin log channel %s", channel_id, exc_info=True
                    )
                    continue

            if channel is None or not hasattr(channel, "send"):
                self.logger.warning("Admin log channel %s is not message-capable", channel_id)
                continue

            try:
                await channel.send(message)
            except Exception:
                self.logger.warning(
                    "Failed to publish action log message to channel %s",
                    channel_id,
                    exc_info=True,
                )

    @property
    def slash_guild_ids(self) -> list[int] | None:
        """Return guild IDs for slash command registration or ``None`` for global.

        Spectre now defaults to global slash-command registration so newly invited
        guilds receive commands immediately after a guild sync. Restricting
        commands to a static guild list prevents commands from appearing in new
        servers where the bot is later invited.
        """

        return None


__all__ = ["SpectreContext"]
