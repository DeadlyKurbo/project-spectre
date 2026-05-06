"""Shared runtime context for the Spectre application."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
import re
from typing import Optional

import logging
import nextcord

from nextcord.ext import commands, tasks
from lazarus import LazarusAI
from server_config import get_dashboard_logging_channels, get_server_config
from spectre.moderation.discord_bridge import DiscordModerationRequest

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

    async def execute_discord_moderation(self, request: DiscordModerationRequest) -> dict[str, object]:
        """
        Execute a moderation action request against Discord.

        The operation is idempotent from the API's perspective by using a stable
        operation key; this method focuses only on performing the requested action.
        """
        guild_id = int(str(request.guild_id or "0"))
        target_id = int(str(request.subject_id or "0"))
        action = str(request.action or "").strip().lower()
        if guild_id <= 0 or target_id <= 0:
            return {"ok": False, "error": "invalid-guild-or-subject-id"}

        guild = self.bot.get_guild(guild_id)
        if guild is None:
            try:
                guild = await self.bot.fetch_guild(guild_id)
            except Exception:
                self.logger.warning("Failed to resolve guild %s for moderation", guild_id, exc_info=True)
                return {"ok": False, "error": "guild-not-found"}

        reason = f"[{request.operation_key}] {request.reason}".strip()
        member = guild.get_member(target_id)
        if member is None:
            try:
                member = await guild.fetch_member(target_id)
            except Exception:
                member = None

        try:
            if action == "timeout":
                if member is None:
                    return {"ok": False, "error": "member-not-found-for-timeout"}
                await member.edit(timeout=datetime.now(UTC) + timedelta(hours=24), reason=reason)
            elif action == "kick":
                if member is None:
                    return {"ok": False, "error": "member-not-found-for-kick"}
                await guild.kick(member, reason=reason)
            elif action in {"ban", "suspension"}:
                user = member
                if user is None:
                    user = await self.bot.fetch_user(target_id)
                await guild.ban(user, reason=reason, delete_message_days=0)
            elif action == "read_only":
                if member is None:
                    return {"ok": False, "error": "member-not-found-for-read-only"}
                # Read-only is represented as communication timeout for 1 hour.
                await member.edit(timeout=datetime.now(UTC) + timedelta(hours=1), reason=reason)
            elif action == "quarantine":
                if member is None:
                    return {"ok": False, "error": "member-not-found-for-quarantine"}
                await member.edit(timeout=datetime.now(UTC) + timedelta(hours=6), reason=reason)
            else:
                return {"ok": False, "error": f"unsupported-action:{action}"}
        except Exception as exc:
            self.logger.warning(
                "Discord moderation action failed op=%s action=%s guild=%s target=%s",
                request.operation_key,
                action,
                guild_id,
                target_id,
                exc_info=True,
            )
            return {"ok": False, "error": str(exc)}

        await self.log_action(
            f"Moderation action `{action}` executed for <@{target_id}> in guild `{guild_id}`.",
            event_type="moderation_action",
            guild_id=guild_id,
        )
        return {
            "ok": True,
            "operationKey": request.operation_key,
            "guildId": str(guild_id),
            "subjectId": str(target_id),
            "action": action,
        }

    async def _resolve_admin_log_channel_ids(
        self, guild_id: int | None = None
    ) -> list[int]:
        """Return admin log channel IDs for the given guild only.

        When guild_id is provided, only channels for that guild are returned.
        When guild_id is None, no channels are returned to prevent cross-server
        log leakage (logs from one server must not appear in another server).
        """
        if guild_id is None:
            return []
        guild_ids: set[int] = {int(guild_id)}

        channel_ids: set[int] = set()
        for gid in guild_ids:
            cfg = get_server_config(int(gid))
            if isinstance(cfg, dict):
                for key in ("ADMIN_LOG_CHANNEL_ID", "SECURITY_LOG_CHANNEL_ID"):
                    raw_channel_id = cfg.get(key)
                    if isinstance(raw_channel_id, int) and raw_channel_id > 0:
                        channel_ids.add(raw_channel_id)
                dashboard_channels = get_dashboard_logging_channels(int(gid))
                admin_log_channel = dashboard_channels.get("admin_log")
                if isinstance(admin_log_channel, int) and admin_log_channel > 0:
                    channel_ids.add(admin_log_channel)

        return sorted(channel_ids)

    async def log_action(
        self,
        message: str,
        *,
        broadcast: bool = True,
        event_type: str | None = None,
        clearance: str | int | None = None,
        guild_id: int | None = None,
    ) -> None:
        """Log actions and mirror them to configured admin channels.

        Optional kwargs:
            event_type: Audit event key (e.g. file_access, file_upload). When set,
                logging is skipped if that event is disabled in ADMIN_AUDIT_EVENTS.
            clearance: User's clearance level (e.g. 5, "Level 5", "High Command").
                Overrides extraction from message text.
            guild_id: Guild ID for audit config lookup.
        """

        if broadcast:
            self.logger.info("Action log entry: %s", message)
        else:
            self.logger.debug("Action log entry: %s", message)
            return

        if event_type is not None:
            if guild_id is not None:
                cfg = get_server_config(guild_id)
                audit_events = cfg.get("ADMIN_AUDIT_EVENTS") if isinstance(cfg, dict) else {}
                if isinstance(audit_events, dict) and audit_events.get(event_type) is False:
                    return
            else:
                enabled = False
                for gid in self.guild_ids:
                    cfg = get_server_config(gid)
                    audit_events = cfg.get("ADMIN_AUDIT_EVENTS") if isinstance(cfg, dict) else {}
                    if isinstance(audit_events, dict) and audit_events.get(event_type) is not False:
                        enabled = True
                        break
                if self.guild_ids and not enabled:
                    return

        channel_ids = await self._resolve_admin_log_channel_ids(guild_id=guild_id)
        if not channel_ids:
            return

        embed = self._build_action_embed(message, clearance=clearance)

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
                # Some channel implementations and API revisions are stricter
                # about ``embeds`` payload handling than ``embed``. Retry with
                # the list-based argument before falling back to plain text.
                try:
                    await channel.send(embeds=[embed])
                    continue
                except Exception:
                    self.logger.warning(
                        "Failed to publish action log embed to channel %s; falling back to plain text",
                        channel_id,
                        exc_info=True,
                    )

                try:
                    await channel.send(message)
                except Exception:
                    self.logger.warning(
                        "Failed to publish action log message to channel %s",
                        channel_id,
                        exc_info=True,
                    )

    def _build_action_embed(
        self, message: str, *, clearance: str | int | None = None
    ) -> nextcord.Embed:
        """Render a normalized admin-operations embed from a plain action message."""

        message = message.strip()
        lowered = message.lower()

        target = self._truncate_embed_value(self._extract_target(message))
        subject = self._truncate_embed_value(self._extract_subject(message))
        clearance_val = self._truncate_embed_value(
            self._format_clearance(clearance) if clearance is not None else self._extract_clearance(message)
        )
        case_id = self._truncate_embed_value(self._extract_case_id(message))
        action_text = self._truncate_embed_value(self._extract_action_text(message))

        # Security breach: unauthorized access attempts. Avoid "denied" alone - it
        # also matches admin workflows (e.g. "denied trainee submission", "denied ID change").
        is_breach = any(
            token in lowered
            for token in (
                "unauthorized",
                "blocked",
                "breach",
                "without clearance",
                "attempted to access",
            )
        )
        # Clearance request: user requesting file access. Avoid bare "request" - it
        # matches "requested changes for trainee submission" and other admin workflows.
        is_request = any(
            token in lowered
            for token in (
                "requested access",
                "requested clearance",
                "pending authorization",
                "clearance request",
            )
        )
        is_success = any(token in lowered for token in ("granted", "successful", "approved", "retrieval", "authorized"))
        is_error = any(token in lowered for token in ("failed", "error", "restore backup error"))
        status = self._truncate_embed_value(self._infer_status(lowered, is_breach=is_breach, is_request=is_request, is_success=is_success))
        severity = self._truncate_embed_value(self._infer_severity(is_breach=is_breach, is_request=is_request, is_success=is_success))

        embed = nextcord.Embed(timestamp=datetime.now(UTC))
        if is_breach:
            embed.title = "SECURITY BREACH"
            embed.description = "Unauthorized file access attempt detected"
            embed.color = 0xFF0000
            embed.add_field(name="Subject", value=subject, inline=True)
            embed.add_field(name="Clearance", value=clearance_val, inline=True)
            embed.add_field(name="Target", value=target, inline=False)
            embed.add_field(name="Case ID", value=case_id, inline=True)
            embed.add_field(name="Status", value=status, inline=True)
            embed.add_field(name="Severity", value=severity, inline=True)
            embed.set_footer(text="SPECTRE Security Core")
            return embed

        if is_request:
            embed.title = "CLEARANCE REQUEST"
            embed.color = 0xFFA500
            embed.add_field(name="Requester", value=subject, inline=True)
            embed.add_field(name="Requested Level", value=clearance_val, inline=True)
            embed.add_field(name="Target", value=target, inline=False)
            embed.add_field(name="Review Status", value=status, inline=False)
            embed.add_field(name="Case ID", value=case_id, inline=True)
            embed.add_field(name="Severity", value=severity, inline=True)
            embed.set_footer(text="SPECTRE Clearance Authority")
            return embed

        if is_success:
            embed.title = "ACCESS GRANTED"
            embed.color = 0x2ECC71
            embed.add_field(name="Agent", value=subject, inline=True)
            embed.add_field(name="Clearance", value=clearance_val, inline=True)
            embed.add_field(name="File", value=target, inline=False)
            embed.add_field(name="Result", value=status, inline=False)
            embed.add_field(name="Case ID", value=case_id, inline=True)
            embed.add_field(name="Severity", value=severity, inline=True)
            embed.set_footer(text="SPECTRE Intelligence Systems")
            return embed

        if is_error:
            embed.title = "SYSTEM ERROR"
            embed.color = 0xE74C3C
            embed.add_field(name="Agent", value=subject, inline=True)
            embed.add_field(name="Action", value=action_text, inline=False)
            embed.add_field(name="Target", value=target, inline=False)
            embed.add_field(name="Status", value=status, inline=True)
            embed.add_field(name="Case ID", value=case_id, inline=True)
            embed.add_field(name="Severity", value=severity, inline=True)
            embed.set_footer(text="SPECTRE Intelligence Grid")
            return embed

        embed.title = "INTELLIGENCE ACCESS"
        embed.color = 0x3498DB
        embed.add_field(name="Agent", value=subject, inline=True)
        embed.add_field(name="Clearance", value=clearance_val, inline=True)
        embed.add_field(name="Action", value=action_text, inline=False)
        embed.add_field(name="Target", value=target, inline=False)
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Case ID", value=case_id, inline=True)
        embed.add_field(name="Severity", value=severity, inline=True)
        embed.set_footer(text="SPECTRE Intelligence Grid")
        return embed

    @staticmethod
    def _format_clearance(clearance: str | int) -> str:
        """Format clearance for display."""
        if isinstance(clearance, int):
            if clearance >= 6:
                return "High Command"
            return f"Level {clearance}"
        return str(clearance)

    @staticmethod
    def _infer_status(lowered_message: str, *, is_breach: bool, is_request: bool, is_success: bool) -> str:
        if is_breach:
            return "BLOCKED"
        if is_request:
            return "Pending authorization"
        if is_success:
            return "Successful retrieval"
        if "failed" in lowered_message or "error" in lowered_message:
            return "Failed"
        return "Recorded"

    @staticmethod
    def _infer_severity(*, is_breach: bool, is_request: bool, is_success: bool) -> str:
        if is_breach:
            return "CRITICAL"
        if is_request:
            return "ELEVATED"
        if is_success:
            return "NORMAL"
        return "INFO"

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
        case_match = re.search(r"\b(SPT-[A-Z]{2}-\d+)\b", message)
        if case_match:
            return case_match.group(1)

        digest = hashlib.sha1(f"{message}|{datetime.now(UTC).date().isoformat()}".encode("utf-8")).hexdigest()
        numeric = int(digest[:8], 16) % 1000
        return f"SPT-SC-{numeric:03d}"

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

    @staticmethod
    def _truncate_embed_value(value: str, limit: int = 1024) -> str:
        """Ensure dynamic embed field values respect Discord limits."""

        cleaned = (value or "N/A").strip()
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 3] + "..."

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
