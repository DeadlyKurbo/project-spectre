"""Shared runtime context for the Spectre application."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import re
from typing import Optional

import logging
import nextcord

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

        embed = self._build_action_embed(message)

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
                await channel.send(embed=embed)
            except Exception:
                self.logger.warning(
                    "Failed to publish action log message to channel %s",
                    channel_id,
                    exc_info=True,
                )

    def _build_action_embed(self, message: str) -> nextcord.Embed:
        """Render a normalized admin-operations embed from a plain action message."""

        lowered = message.lower()
        is_breach = any(
            token in lowered
            for token in (
                "unauthorized",
                "blocked",
                "breach",
                "denied",
                "without clearance",
                "attempted to access",
            )
        )
        is_request = any(
            token in lowered for token in ("request", "pending authorization", "clearance request")
        )
        is_success = any(
            token in lowered for token in ("granted", "successful", "approved", "retrieval", " accessed ")
        )

        if is_breach:
            title = "SECURITY BREACH"
            color = 0xFF0000
            status = "BLOCKED"
            severity = "CRITICAL"
            footer = "Federal Defense Directorate Security Core"
        elif is_request:
            title = "CLEARANCE REQUEST"
            color = 0xFFA500
            status = "Pending authorization"
            severity = "ELEVATED"
            footer = "FDD Clearance Authority"
        elif is_success:
            title = "ACCESS GRANTED"
            color = 0x2ECC71
            status = "Successful"
            severity = "NORMAL"
            footer = "FDD Intelligence Systems"
        else:
            title = "INTELLIGENCE ACCESS"
            color = 0x3498DB
            status = "Recorded"
            severity = "INFO"
            footer = "FDD Intelligence Grid"

        target_match = re.search(r"\b[\w.-]+/[\w./-]+\b", message)
        target = target_match.group(0) if target_match else "N/A"

        agent_match = re.search(r"(@[^\s]+|<@!?\d+>)", message)
        agent = agent_match.group(0) if agent_match else "Unspecified"

        clearance_match = re.search(r"(?:clearance|level)\s*[-:]?\s*(\d\+?)", lowered)
        clearance = f"Level {clearance_match.group(1)}" if clearance_match else "Unknown"

        case_match = re.search(r"(FDD-SC-[A-Z0-9-]+)", message, flags=re.IGNORECASE)
        if case_match:
            case_id = case_match.group(1).upper()
        else:
            digest = hashlib.sha1(
                f"{message}|{datetime.now(UTC).isoformat(timespec='seconds')}".encode("utf-8")
            ).hexdigest()
            case_id = f"FDD-SC-{digest[:6].upper()}"

        embed = nextcord.Embed(title=title, color=color, timestamp=datetime.now(UTC))
        embed.add_field(name="Agent", value=agent, inline=True)
        embed.add_field(name="Clearance", value=clearance, inline=True)
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Action", value=message[:1024], inline=False)
        embed.add_field(name="Target", value=target, inline=False)
        embed.add_field(name="Severity", value=severity, inline=True)
        embed.add_field(name="Case ID", value=case_id, inline=True)
        embed.set_footer(text=footer)
        return embed

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
