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

        message = message.strip()
        lowered = message.lower()

        target = self._extract_target(message)
        subject = self._extract_subject(message)
        clearance = self._extract_clearance(message)
        case_id = self._extract_case_id(message)
        action_text = self._extract_action_text(message)

        is_breach = any(token in lowered for token in ("unauthorized", "blocked", "breach", "denied", "without clearance", "attempted to access"))
        is_request = any(token in lowered for token in ("request", "pending authorization", "clearance request"))
        is_success = any(token in lowered for token in ("granted", "successful", "approved", "retrieval", "accessed"))

        embed = nextcord.Embed(timestamp=datetime.now(UTC))
        if is_breach:
            embed.title = "SECURITY BREACH"
            embed.description = "Unauthorized file access attempt detected"
            embed.color = 0xFF0000
            embed.add_field(name="Subject", value=subject, inline=True)
            embed.add_field(name="Clearance", value=clearance, inline=True)
            embed.add_field(name="Target", value=target, inline=False)
            embed.add_field(name="Case ID", value=case_id, inline=True)
            embed.add_field(name="Status", value="BLOCKED", inline=True)
            embed.add_field(name="Severity", value="CRITICAL", inline=True)
            embed.set_footer(text="Federal Defense Directorate Security Core")
            return embed

        if is_request:
            embed.title = "CLEARANCE REQUEST"
            embed.color = 0xFFA500
            embed.add_field(name="Requester", value=subject, inline=True)
            embed.add_field(name="Requested Level", value=clearance, inline=True)
            embed.add_field(name="Target", value=target, inline=False)
            embed.add_field(name="Review Status", value="Pending authorization", inline=False)
            embed.add_field(name="Case ID", value=case_id, inline=True)
            embed.add_field(name="Severity", value="ELEVATED", inline=True)
            embed.set_footer(text="FDD Clearance Authority")
            return embed

        if is_success:
            embed.title = "ACCESS GRANTED"
            embed.color = 0x2ECC71
            embed.add_field(name="Agent", value=subject, inline=True)
            embed.add_field(name="Clearance", value=clearance, inline=True)
            embed.add_field(name="File", value=target, inline=False)
            embed.add_field(name="Result", value="Successful retrieval", inline=False)
            embed.add_field(name="Case ID", value=case_id, inline=True)
            embed.add_field(name="Severity", value="NORMAL", inline=True)
            embed.set_footer(text="FDD Intelligence Systems")
            return embed

        embed.title = "INTELLIGENCE ACCESS"
        embed.color = 0x3498DB
        embed.add_field(name="Agent", value=subject, inline=True)
        embed.add_field(name="Clearance", value=clearance, inline=True)
        embed.add_field(name="Action", value=action_text, inline=False)
        embed.add_field(name="Target", value=target, inline=False)
        embed.add_field(name="Status", value="Recorded", inline=True)
        embed.add_field(name="Case ID", value=case_id, inline=True)
        embed.add_field(name="Severity", value="INFO", inline=True)
        embed.set_footer(text="FDD Intelligence Grid")
        return embed

    @staticmethod
    def _extract_target(message: str) -> str:
        target_match = re.search(r"`([^`]+)`", message)
        if target_match:
            return target_match.group(1)
        fallback_match = re.search(r"\b[\w.-]+/[\w./-]+\b", message)
        if fallback_match:
            return fallback_match.group(0)
        return "N/A"

    @staticmethod
    def _extract_subject(message: str) -> str:
        mention_match = re.search(r"(<@!?\d+>|@[^\s]+)", message)
        if mention_match:
            return mention_match.group(1)
        return "Unspecified"

    @staticmethod
    def _extract_clearance(message: str) -> str:
        clearance_match = re.search(r"\b(?:level|clearance)\s*[-:]?\s*(\d+)\b", message, re.IGNORECASE)
        if clearance_match:
            return f"Level {clearance_match.group(1)}"

        lowered = message.lower()
        if "without clearance" in lowered:
            return "Insufficient"
        if "trainee" in lowered:
            return "Trainee"
        if "high command" in lowered:
            return "High Command"
        return "Level Unknown"

    @staticmethod
    def _extract_case_id(message: str) -> str:
        case_match = re.search(r"\b(FDD-[A-Z]{2}-\d+)\b", message)
        if case_match:
            return case_match.group(1)

        digest = hashlib.sha1(f"{message}|{datetime.now(UTC).date().isoformat()}".encode("utf-8")).hexdigest()
        numeric = int(digest[:8], 16) % 1000
        return f"FDD-SC-{numeric:03d}"

    @staticmethod
    def _extract_action_text(message: str) -> str:
        action_text = message
        target_match = re.search(r"`[^`]+`", action_text)
        if target_match:
            action_text = f"{action_text[:target_match.start()]}{action_text[target_match.end():]}"
        action_text = re.sub(r"\s+", " ", action_text).strip(" .")
        if len(action_text) > 1024:
            return action_text[:1021] + "..."
        return action_text or "Activity logged"

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
